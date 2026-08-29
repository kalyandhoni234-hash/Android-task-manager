"""Tests for the Copilot context builder."""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from android_task_manager.applications.models import AppCategory, AppInfo, ApplicationSnapshot
from android_task_manager.battery.models import BatteryHealth, BatterySnapshot, BatteryStatus
from android_task_manager.copilot.context import build_context
from android_task_manager.copilot.models import ProcessSafetyClass
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.health.models import (
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    DeviceHealth,
    Finding,
    HealthSeverity,
    HealthStatus,
)
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot
from android_task_manager.recommend.models import Recommendation
from android_task_manager.storage.models import StorageSnapshot


@pytest.fixture
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def _make_process(
    pid: int,
    name: str,
    category: ProcessCategory = ProcessCategory.USER,
    cpu: float | None = None,
    mem: float | None = None,
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=10000 + pid,
        state="S",
        cpu_percent=cpu,
        memory_percent=mem,
        category=category,
    )


def test_build_context_disconnected() -> None:
    ctx = build_context(current_page="overview", connected=False)
    assert ctx.connected is False
    assert ctx.current_page == "overview"
    assert ctx.device_label is None
    assert ctx.cpu_percent is None


def test_build_context_full_snapshots() -> None:
    cpu = CPUSnapshot(
        timestamp=time.time(),
        aggregate_utilization_percent=65.3,
        cores=[],
    )
    mem = MemorySnapshot(
        timestamp=time.time(),
        total_kb=4_000_000,
        free_kb=500_000,
        available_kb=2_000_000,
        buffers_kb=100_000,
        cached_kb=800_000,
        swap_cached_kb=0,
    )
    battery = BatterySnapshot(
        timestamp=time.time(),
        level_percent=72.0,
        scale=100,
        voltage_mv=4200,
        temperature_c=35.0,
        status=BatteryStatus.CHARGING,
        status_raw=2,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=False,
        usb_powered=True,
        wireless_powered=False,
        technology="Li-poly",
        charge_counter=None,
    )
    storage = StorageSnapshot(
        timestamp=time.time(),
        mount="/data",
        total_kb=64_000_000,
        used_kb=40_000_000,
        available_kb=24_000_000,
    )
    procs = ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            _make_process(100, "com.example.app1", cpu=45.0, mem=12.0),
            _make_process(200, "com.example.app2", cpu=20.0, mem=8.0),
            _make_process(300, "[kworker/0:1]", category=ProcessCategory.KERNEL_THREAD, cpu=1.0),
        ],
    )
    apps = ApplicationSnapshot(
        timestamp=time.time(),
        applications=[
            AppInfo(package_name="com.example.app1", category=AppCategory.USER),
            AppInfo(package_name="com.android.systemui", category=AppCategory.SYSTEM),
        ],
    )
    findings = [
        Finding(
            severity=HealthSeverity.WARNING,
            component=COMPONENT_CPU,
            title="CPU elevated",
            explanation="CPU above threshold",
            evidence="65.3%",
            recommendation="Investigate",
            timestamp=time.time(),
        ),
        Finding(
            severity=HealthSeverity.CRITICAL,
            component=COMPONENT_MEMORY,
            title="Memory high",
            explanation="Memory above threshold",
            evidence="50%",
            recommendation="Close apps",
            timestamp=time.time(),
        ),
    ]
    health = DeviceHealth(
        overall_score=70.0,
        status=HealthStatus.WARNING,
        components={},
        findings=findings,
    )
    recs = (
        Recommendation(
            recommendation_id="REC-001",
            finding_ref="CPU elevated",
            title="Investigate CPU",
            rationale="CPU is high",
            severity="warning",
        ),
    )
    ctx = build_context(
        current_page="processes",
        connected=True,
        device_label="Pixel 7",
        android_version="14",
        cpu=cpu,
        memory=mem,
        battery=battery,
        storage=storage,
        processes=procs,
        app_snapshot=apps,
        health=health,
        recommendations=recs,
    )
    assert ctx.connected is True
    assert ctx.device_label == "Pixel 7"
    assert ctx.android_version == "14"
    assert ctx.cpu_percent == 65.3
    assert ctx.memory_used_percent is not None
    assert abs(ctx.memory_used_percent - 50.0) < 0.1
    assert ctx.memory_total_kb == 4_000_000
    assert ctx.battery_level_percent == 72.0
    assert ctx.battery_status == "Charging"
    assert ctx.storage_used_percent is not None
    assert abs(ctx.storage_used_percent - 62.5) < 0.1
    assert ctx.process_count == 3
    assert ctx.installed_app_count == 2
    assert ctx.user_app_count == 1
    assert ctx.health_status == "warning"
    assert ctx.health_score == 70.0
    assert len(ctx.health_findings) == 2
    severities = {f.severity for f in ctx.health_findings}
    assert "critical" in severities
    assert "warning" in severities
    assert len(ctx.top_processes) == 2
    assert ctx.top_processes[0].category == ProcessSafetyClass.SAFE_CANDIDATE
    assert len(ctx.recommendations) == 1


def test_build_context_kernel_threads_excluded() -> None:
    procs = ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            _make_process(1, "[kworker/0:1]", category=ProcessCategory.KERNEL_THREAD),
            _make_process(2, "system_server", category=ProcessCategory.SYSTEM),
            _make_process(3, "com.example.app", category=ProcessCategory.USER, cpu=10.0),
        ],
    )
    ctx = build_context(
        current_page="overview",
        connected=True,
        processes=procs,
    )
    assert len(ctx.top_processes) == 1
    assert ctx.top_processes[0].name == "com.example.app"
    assert ctx.top_processes[0].category == ProcessSafetyClass.SAFE_CANDIDATE


def test_build_context_none_snapshots() -> None:
    ctx = build_context(
        current_page="overview",
        connected=True,
        device_label="Test Device",
    )
    assert ctx.cpu_percent is None
    assert ctx.memory_used_percent is None
    assert ctx.battery_level_percent is None
    assert ctx.storage_used_percent is None
    assert ctx.process_count is None
    assert ctx.installed_app_count is None


def test_copilot_page_context_connected(qtapp: QApplication) -> None:
    """CopilotPage.update_context displays connected device label."""
    from android_task_manager.gui.copilot_page import CopilotPage

    page = CopilotPage()
    page.update_context(
        device_label="vivo V2026",
        connected=True,
        page="overview",
        cpu_percent=42.0,
        memory_percent=68.0,
    )
    text = page._context_label.text()
    assert "vivo V2026" in text
    assert "No device" not in text
    assert "CPU 42%" in text
    assert "RAM 68%" in text


def test_copilot_page_context_disconnected(qtapp: QApplication) -> None:
    """CopilotPage.update_context shows no-device when disconnected."""
    from android_task_manager.gui.copilot_page import CopilotPage

    page = CopilotPage()
    page.update_context(
        device_label=None,
        connected=False,
        page="overview",
    )
    text = page._context_label.text()
    assert "No device connected" in text


def test_copilot_page_context_connects_after_creation(qtapp: QApplication) -> None:
    """CopilotPage context updates when device connects after page creation."""
    from android_task_manager.gui.copilot_page import CopilotPage

    page = CopilotPage()
    assert "No device" in page._context_label.text()

    page.update_context(
        device_label="Pixel 7",
        connected=True,
        page="overview",
    )
    text = page._context_label.text()
    assert "Pixel 7" in text
    assert "No device" not in text


def test_copilot_page_context_disconnects_after_creation(qtapp: QApplication) -> None:
    """CopilotPage context updates when device disconnects."""
    from android_task_manager.gui.copilot_page import CopilotPage

    page = CopilotPage()
    page.update_context(
        device_label="Pixel 7",
        connected=True,
        page="overview",
    )
    assert "Pixel 7" in page._context_label.text()

    page.update_context(
        device_label=None,
        connected=False,
        page="overview",
    )
    assert "No device connected" in page._context_label.text()


def test_copilot_page_context_page_tracking(qtapp: QApplication) -> None:
    """CopilotPage context shows current page."""
    from android_task_manager.gui.copilot_page import CopilotPage

    page = CopilotPage()
    page.update_context(
        device_label="Pixel 7",
        connected=True,
        page="processes",
    )
    assert "Page: processes" in page._context_label.text()
