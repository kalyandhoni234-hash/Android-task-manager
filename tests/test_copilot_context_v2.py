"""Tests for the rich Copilot context v2 (device, cpu, memory, battery,
storage, network, applications, health, diagnostics, performance, page,
candidates, freshness)."""

from __future__ import annotations

import time

from android_task_manager.applications.models import AppCategory, AppInfo, ApplicationSnapshot
from android_task_manager.background.models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
    ForegroundSnapshot,
)
from android_task_manager.battery.models import BatteryHealth, BatterySnapshot, BatteryStatus
from android_task_manager.copilot.context import build_context
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.device.models import DeviceInformation
from android_task_manager.diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticSeverity,
)
from android_task_manager.health.models import (
    COMPONENT_CPU,
    DeviceHealth,
    Finding,
    HealthSeverity,
    HealthStatus,
)
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.network.models import (
    NetworkInterfaceSnapshot,
    NetworkSnapshot,
    NetworkThroughput,
)
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot
from android_task_manager.storage.models import StorageSnapshot


def _device_info() -> DeviceInformation:
    return DeviceInformation(
        manufacturer="vivo",
        model="V2026",
        android_version="11",
        uptime_seconds=3600.0,
    )


def _battery() -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=time.time(),
        level_percent=85.0,
        scale=100,
        voltage_mv=4100,
        temperature_c=36.5,
        status=BatteryStatus.CHARGING,
        status_raw=2,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=True,
        usb_powered=False,
        wireless_powered=False,
        technology="Li-poly",
        charge_counter=None,
    )


def _memory() -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=time.time(),
        total_kb=4_000_000,
        free_kb=800_000,
        available_kb=900_000,
        buffers_kb=100_000,
        cached_kb=1_000_000,
        swap_cached_kb=0,
    )


def _storage() -> StorageSnapshot:
    return StorageSnapshot(
        timestamp=time.time(),
        mount="/data",
        total_kb=64_000_000,
        used_kb=48_000_000,
        available_kb=16_000_000,
    )


def _network() -> NetworkSnapshot:
    return NetworkSnapshot(
        timestamp=time.time(),
        interfaces=[
            NetworkInterfaceSnapshot(
                name="wlan0",
                rx_bytes=1_000_000,
                tx_bytes=2_000_000,
                rx_packets=10,
                tx_packets=20,
                rx_errors=0,
                tx_errors=0,
                rx_drops=0,
                tx_drops=0,
            )
        ],
        aggregate_throughput=NetworkThroughput(50_000.0, 100_000.0),
    )


def _cpu() -> CPUSnapshot:
    return CPUSnapshot(timestamp=time.time(), aggregate_utilization_percent=42.0, cores=[])


def _processes() -> ProcessSnapshot:
    return ProcessSnapshot(
        timestamp=time.time(),
        processes=[
            ProcessInfo(
                pid=1,
                name="com.instagram.android",
                uid=10000,
                state="S",
                cpu_percent=5.0,
                memory_percent=11.0,
                category=ProcessCategory.USER,
            ),
            ProcessInfo(
                pid=2,
                name="system_server",
                uid=1000,
                state="S",
                cpu_percent=2.0,
                memory_percent=3.0,
                category=ProcessCategory.SYSTEM,
            ),
            ProcessInfo(
                pid=3,
                name="[kworker/0:1]",
                uid=0,
                state="S",
                cpu_percent=0.5,
                memory_percent=0.0,
                category=ProcessCategory.KERNEL_THREAD,
            ),
        ],
    )


def _apps() -> ApplicationSnapshot:
    return ApplicationSnapshot(
        timestamp=time.time(),
        applications=[
            AppInfo(package_name="com.instagram.android", category=AppCategory.USER, enabled=True),
            AppInfo(package_name="com.android.systemui", category=AppCategory.SYSTEM, enabled=True),
        ],
    )


def _health() -> DeviceHealth:
    return DeviceHealth(
        overall_score=70.0,
        status=HealthStatus.WARNING,
        components={},
        findings=[
            Finding(
                severity=HealthSeverity.CRITICAL,
                component=COMPONENT_CPU,
                title="CPU saturated",
                explanation="CPU is high",
                evidence="42%",
                recommendation="Investigate",
                timestamp=time.time(),
            )
        ],
    )


def _diagnostics() -> DiagnosticReport:
    return DiagnosticReport(
        findings=(
            DiagnosticFinding(
                severity=DiagnosticSeverity.CRITICAL,
                category=DiagnosticCategory.STORAGE,
                title="Storage nearly full",
                what="Storage is nearly full",
                why="It is above the threshold",
                evidence="/data usage: 75%",
                recommended_action="Free storage",
            ),
        )
    )


def _background(foreground: str | None = "com.instagram.android") -> BackgroundAppsSnapshot:
    return BackgroundAppsSnapshot(
        timestamp=time.time(),
        entries=[
            BackgroundAppEntry(
                package_name="com.instagram.android",
                uid=10000,
                pids=(1,),
                cpu_percent=5.0,
                memory_percent=11.0,
                memory_kb=440_000,
                state=BackgroundAppState.BACKGROUND,
            )
        ],
    )


def _fg(foreground: str | None = "com.arena.zooba") -> ForegroundSnapshot:
    return ForegroundSnapshot(
        timestamp=time.time(), package_name=foreground, available=foreground is not None
    )


def test_device_context() -> None:
    ctx = build_context(
        current_page="device",
        connected=True,
        device_label="vivo V2026",
        android_version="11",
        device_info=_device_info(),
    )
    assert ctx.device_model == "V2026"
    assert ctx.device_manufacturer == "vivo"
    assert ctx.uptime_seconds == 3600.0


def test_cpu_context() -> None:
    ctx = build_context(current_page="overview", connected=True, cpu=_cpu())
    assert ctx.cpu_percent == 42.0


def test_memory_context() -> None:
    ctx = build_context(current_page="overview", connected=True, memory=_memory())
    assert abs(ctx.memory_used_percent - 77.5) < 0.1
    assert ctx.memory_total_kb == 4_000_000
    assert ctx.memory_available_kb == 900_000


def test_battery_context() -> None:
    ctx = build_context(current_page="overview", connected=True, battery=_battery())
    assert ctx.battery_level_percent == 85.0
    assert ctx.battery_status == "Charging"
    assert ctx.battery_temperature_c == 36.5
    assert ctx.battery_health == "Good"


def test_storage_context() -> None:
    ctx = build_context(current_page="overview", connected=True, storage=_storage())
    assert abs(ctx.storage_used_percent - 75.0) < 0.1
    assert ctx.storage_available_kb == 16_000_000


def test_network_context() -> None:
    ctx = build_context(current_page="network", connected=True, network=_network())
    assert ctx.network_connected is True
    assert ctx.network_throughput_rx_bps == 50_000.0
    assert ctx.network_throughput_tx_bps == 100_000.0


def test_applications_context() -> None:
    ctx = build_context(
        current_page="applications",
        connected=True,
        app_snapshot=_apps(),
        user_packages={"com.instagram.android"},
    )
    assert ctx.installed_app_count == 2
    assert ctx.user_app_count == 1
    assert len(ctx.applications) == 2
    by_name = {a.package_name: a for a in ctx.applications}
    assert by_name["com.instagram.android"].category == "user"
    # User app has force-stop capability exposed (deterministic).
    assert by_name["com.instagram.android"].capability == "force_stop"


def test_health_context() -> None:
    ctx = build_context(current_page="health", connected=True, health=_health())
    assert ctx.health_status == "warning"
    assert ctx.health_score == 70.0
    assert ctx.health_findings[0].severity == "critical"
    assert ctx.health_findings[0].component == COMPONENT_CPU


def test_diagnostics_context() -> None:
    ctx = build_context(current_page="diagnostics", connected=True, diagnostics=_diagnostics())
    assert len(ctx.diagnostics_findings) == 1
    assert ctx.diagnostics_findings[0].severity == "critical"
    assert ctx.diagnostics_findings[0].component == "storage"
    assert "Free storage" in ctx.diagnostics_findings[0].recommendation


def test_performance_context() -> None:
    ctx = build_context(
        current_page="performance",
        connected=True,
        performance_score=62,
        performance_pressured=("memory", "storage"),
    )
    assert ctx.performance_score == 62
    assert ctx.performance_pressured == ("memory", "storage")


def test_page_context() -> None:
    ctx = build_context(current_page="processes", connected=True)
    assert ctx.current_page == "processes"


def test_freshness_timestamp() -> None:
    ts = time.time()
    ctx = build_context(current_page="overview", connected=True, context_timestamp=ts)
    assert ctx.context_timestamp == ts


def test_candidates_exposed_only_for_gaming_intent() -> None:
    ctx = build_context(
        current_page="copilot",
        connected=True,
        query="I want to play Zooba. What should I close?",
        processes=_processes(),
        app_snapshot=_apps(),
        background=_background(),
        foreground=_fg(),
        user_packages={"com.instagram.android", "com.android.systemui"},
        memory=_memory(),
    )
    assert ctx.intent == "gaming"
    assert len(ctx.kill_candidates) >= 1
    assert any(c.name == "com.instagram.android" for c in ctx.kill_candidates)
    # Protected exists for gaming intent.
    assert ctx.protected_processes


def test_candidates_not_exposed_for_non_action_intent() -> None:
    ctx = build_context(
        current_page="copilot",
        connected=True,
        query="Why is my battery draining?",
        processes=_processes(),
        app_snapshot=_apps(),
        background=_background(),
        foreground=_fg(),
        user_packages={"com.instagram.android", "com.android.systemui"},
        memory=_memory(),
    )
    assert ctx.intent == "battery"
    assert ctx.kill_candidates == ()
    assert ctx.protected_processes == ()


def test_kernel_and_system_processes_not_safe_candidates() -> None:
    ctx = build_context(
        current_page="processes",
        connected=True,
        processes=_processes(),
        user_packages=set(),
    )
    for p in ctx.top_processes:
        assert p.category.value != "critical_system"
        assert p.category.value != "system_process"
    names = [p.name for p in ctx.top_processes]
    assert "system_server" not in names
    assert "[kworker/0:1]" not in names


def test_connected_offline_uses_none() -> None:
    ctx = build_context(current_page="overview", connected=False)
    assert ctx.connected is False
    assert ctx.cpu_percent is None
