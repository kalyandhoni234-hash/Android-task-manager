"""Device-free integration tests for the performance monitoring pipeline.

These verify that the existing MonitorWorker snapshot flow is consumed
correctly by the v0.9 performance domain:

* canonical metrics (cpu/memory/battery/storage) are ingested without
  fabricating missing values;
* process pressure + application correlation reuse existing identity;
* the session lifecycle (connect / sample / disconnect / reconnect) is honoured;
* findings are deduplicated across ticks (no per-tick flood);
* timeline lifecycle events are emitted (start / recover) without spam;
* no new QTimer / MonitorWorker / subprocess / ADB appears in the layer.

The Qt adapter is exercised with the project's ``qtapp`` fixture (a single
shared ``QApplication``), while the pure ``PerformanceOrchestrator`` is tested
directly for determinism.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from android_task_manager.background.models import (  # noqa: E402
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
)
from android_task_manager.battery.models import (  # noqa: E402
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUSnapshot  # noqa: E402
from android_task_manager.diagnostics.models import (  # noqa: E402
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticSeverity,
)
from android_task_manager.gui.monitor import ConnectionState  # noqa: E402
from android_task_manager.gui.performance_integration import (  # noqa: E402
    PerformanceIntegration,
)
from android_task_manager.memory.models import MemorySnapshot  # noqa: E402
from android_task_manager.performance import (  # noqa: E402
    ConditionTracker,
    PerformanceOrchestrator,
    PerformanceSession,
)
from android_task_manager.performance.events import PerformanceEventType  # noqa: E402
from android_task_manager.performance.orchestrator import OrchestratorResult  # noqa: E402
from android_task_manager.performance.translation import (  # noqa: E402
    app_loads_from_background,
)
from android_task_manager.process.models import ProcessSnapshot  # noqa: E402
from android_task_manager.storage.models import StorageSnapshot  # noqa: E402


@pytest.fixture
def qtapp() -> QApplication:
    return QApplication.instance() or QApplication([])


# ----------------------------------------------------------------------
# Snapshot factories (pure dataclasses, no device)
# ----------------------------------------------------------------------

def _cpu(pct: float, ts: float = 0.0) -> CPUSnapshot:
    return CPUSnapshot(timestamp=ts, aggregate_utilization_percent=pct, cores=())


def _mem(pct: float, ts: float = 0.0) -> MemorySnapshot:
    total = 1000
    avail = int(round(total * (1 - pct / 100.0)))
    return MemorySnapshot(
        timestamp=ts, total_kb=total, free_kb=0, available_kb=avail,
        buffers_kb=0, cached_kb=0, swap_cached_kb=0,
    )


def _battery(pct: float | None, ts: float = 0.0) -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=ts, level_percent=pct,
        scale=100, voltage_mv=4000, temperature_c=25.0,
        status=BatteryStatus.DISCHARGING, status_raw=3,
        health=BatteryHealth.GOOD, health_raw=2,
        present=True, ac_powered=False, usb_powered=False,
        wireless_powered=False, technology="Li-ion", charge_counter=1000,
    )


def _storage(pct: float, ts: float = 0.0) -> StorageSnapshot:
    total = 1000
    used = int(round(total * pct / 100.0))
    return StorageSnapshot(
        timestamp=ts, mount="/data", total_kb=total,
        used_kb=used, available_kb=total - used,
    )


def _processes(n: int, ts: float = 0.0) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=ts, processes=list(range(n)))


def _background() -> BackgroundAppsSnapshot:
    return BackgroundAppsSnapshot(
        timestamp=0.0,
        entries=[
            BackgroundAppEntry(
                package_name="com.example.heavy", label="Heavy App",
                uid=10001, pids=(1, 2), cpu_percent=40.0, memory_percent=20.0,
                memory_kb=200, state=BackgroundAppState.BACKGROUND,
            ),
            BackgroundAppEntry(
                package_name="com.example.light", label="Light App",
                uid=10002, pids=(3,), cpu_percent=2.0, memory_percent=1.0,  # placeholder
                memory_kb=10, state=BackgroundAppState.BACKGROUND,
            ),
        ],
    )


def _dummy_finding() -> DiagnosticFinding:
    return DiagnosticFinding(
        severity=DiagnosticSeverity.WARNING,
        category=DiagnosticCategory.CPU,
        title="CPU elevated",
        what="x", why="y", evidence="z", recommended_action="a",
    )


# ----------------------------------------------------------------------
# A. Canonical metric ingestion
# ----------------------------------------------------------------------

def test_orchestrator_ingests_canonical_metrics():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    res = o.ingest(
        cpu=_cpu(50.0, 1.0), memory=_mem(40.0, 1.0), battery=_battery(80.0, 1.0),
        storage=_storage(60.0, 1.0), timestamp=1.0,
    )
    assert isinstance(res, OrchestratorResult)
    # No breach at healthy levels -> no findings, but evidence is produced.
    assert res.findings == ()
    assert len(res.evidence) > 0
    cpu_win = o.session.window_for("cpu")
    assert cpu_win.latest("cpu") == pytest.approx(50.0)


# ----------------------------------------------------------------------
# B. Missing metrics are not fabricated
# ----------------------------------------------------------------------

def test_missing_metrics_stay_none():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    for i in range(5):
        o.ingest(cpu=_cpu(10.0, float(i)), timestamp=float(i))
    mem_win = o.session.window_for("memory")
    assert mem_win.is_empty
    assert o.session.window_for("cpu").average("cpu") == pytest.approx(10.0)


def test_missing_metrics_no_false_finding():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    res = o.ingest(timestamp=1.0)
    assert res.findings == ()
    assert res.events == ()


# ----------------------------------------------------------------------
# C. Process ingestion + D. application correlation
# ----------------------------------------------------------------------

def test_process_and_application_pressure():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    o.set_background_apps(_background())
    for i in range(5):
        o.ingest(
            cpu=_cpu(20.0, float(i)),
            processes=_processes(450, float(i)),
            background_apps=_background(),
            timestamp=float(i),
        )
    assert o.session.window_for("process_count").latest("process_count") == 450.0
    bg = o._last_background_apps()
    assert bg is not None
    assert bg.entries[0].package_name == "com.example.heavy"


def test_application_missing_label_is_not_fabricated():
    snap = BackgroundAppsSnapshot(
        timestamp=0.0,
        entries=[
            BackgroundAppEntry(
                package_name="com.example.unknown", label=None,
                uid=10003, pids=(9,), cpu_percent=10.0, memory_percent=5.0,
                memory_kb=50, state=BackgroundAppState.BACKGROUND,
            ),
        ],
    )
    loads = app_loads_from_background(snap)
    assert loads[0][0] == "com.example.unknown"
    assert loads[0][1] is None


# ----------------------------------------------------------------------
# E. Lifecycle
# ----------------------------------------------------------------------

def test_lifecycle_connect_disconnect_reconnect():
    o = PerformanceOrchestrator()
    o.begin_session("A", timestamp=0.0)
    o.ingest(cpu=_cpu(50.0, 1.0), timestamp=1.0)
    assert o.session.device_serial == "A"
    assert not o.session.is_empty
    o.end_session()
    assert o.session.is_empty
    assert o.session.device_serial is None
    o.begin_session("B", timestamp=10.0)
    o.ingest(cpu=_cpu(12.0, 11.0), timestamp=11.0)
    assert o.session.device_serial == "B"
    assert o.session.window_for("cpu").latest("cpu") == pytest.approx(12.0)


# ----------------------------------------------------------------------
# F. Finding deduplication
# ----------------------------------------------------------------------

def test_sustained_cpu_pressure_emits_one_finding():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    started_findings = []
    for i in range(30):
        res = o.ingest(cpu=_cpu(95.0 + (i % 5), float(i)), timestamp=float(i))
        started_findings.extend(res.findings)
    assert len(started_findings) == 1
    assert started_findings[0].category.value == "cpu"


def test_recovery_emits_recovered_event():
    # Small CPU window so recovery occurs quickly once the metric clears.
    o = PerformanceOrchestrator(session=PerformanceSession(cpu_max_samples=8))
    o.begin_session("SERIAL", timestamp=0.0)
    for i in range(5):
        o.ingest(cpu=_cpu(95.0 + (i % 5), float(i)), timestamp=float(i))
    recovered = []
    for i in range(5, 15):
        res = o.ingest(cpu=_cpu(5.0 + (i % 5), float(i)), timestamp=float(i))
        recovered.extend(res.events)
    assert any(e.event_type is PerformanceEventType.CPU_PRESSURE for e in recovered)
    assert any("recovered" in e.title for e in recovered)


def test_no_event_spam_during_sustained_pressure():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    total_events = []
    for i in range(30):
        res = o.ingest(cpu=_cpu(95.0 + (i % 5), float(i)), timestamp=float(i))
        total_events.extend(res.events)
    # started (1) + at most one throttled ACTIVE (60s monitor interval) = < 10.
    assert len(total_events) < 10


# ----------------------------------------------------------------------
# G. Timeline events via adapter
# ----------------------------------------------------------------------

def test_adapter_emits_events_without_spam(qtapp: QApplication) -> None:
    adapter = PerformanceIntegration()
    findings: list = []
    events: list = []
    adapter.findings_ready.connect(lambda f: findings.extend(f))
    adapter.events_ready.connect(lambda e: events.extend(e))
    adapter.on_serial_ready("SERIAL")
    for i in range(30):
        adapter.on_snapshots(_cpu(95.0 + (i % 5), float(i)), _mem(10.0, float(i)),
                              _processes(10, float(i)), _battery(80.0, float(i)), None)
    assert len(findings) == 1
    assert 1 <= len(events) < 10


def test_adapter_disconnect_clears_live_session(qtapp: QApplication) -> None:
    adapter = PerformanceIntegration()
    adapter.on_serial_ready("SERIAL")
    adapter.on_snapshots(_cpu(50.0, 1.0), _mem(10.0, 1.0), _processes(10, 1.0),
                         _battery(80.0, 1.0), None)
    assert not adapter.orchestrator.session.is_empty
    adapter.on_connection_changed(ConnectionState.DISCONNECTED, "lost")
    assert adapter.orchestrator.session.is_empty


# ----------------------------------------------------------------------
# H. Threading / no extra polling invariants (source-level)
# ----------------------------------------------------------------------

def test_performance_layer_has_no_polling_imports():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "android_task_manager"
    forbidden = ("QTimer", "MonitorWorker", "subprocess", "adb")
    checked = 0
    for path in (root / "performance").rglob("*.py"):
        checked += 1
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token} found in {path.name}"
    assert checked > 0


def test_condition_tracker_resets_on_disconnect():
    t = ConditionTracker()
    step = t.update([("cpu:warning", _dummy_finding(), "cpu")], now=1.0)
    assert len(step.started) == 1
    t.reset()
    assert t.active_keys == ()


def test_adapter_does_not_duplicate_inventory_collection():
    import android_task_manager.gui.performance_integration as mod

    text = open(mod.__file__, encoding="utf-8").read()
    assert "build_background_apps" not in text
    assert "AppInfo" not in text
    assert "apk_label" not in text
