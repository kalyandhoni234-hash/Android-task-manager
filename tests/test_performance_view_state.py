"""Tests for the orchestrator's render-ready ``view_state`` (Phase 3 domain).

These lock the single object the GUI renders: overall pressure state, per-metric
cards (with baseline/delta/occupancy), application correlation from already-
resolved identity, and lifecycle events that *accumulate* across ticks (so a
steady-state tick never erases an earlier STARTED/RECOVERED transition).

No QTimer / MonitorWorker / ADB — the orchestrator is driven directly.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
from android_task_manager.memory.models import MemorySnapshot  # noqa: E402
from android_task_manager.performance.orchestrator import PerformanceOrchestrator  # noqa: E402
from android_task_manager.process.models import ProcessSnapshot  # noqa: E402
from android_task_manager.storage.models import StorageSnapshot  # noqa: E402


def _cpu(pct, ts=0.0):
    return CPUSnapshot(timestamp=ts, aggregate_utilization_percent=pct, cores=())


def _mem(pct, ts=0.0):
    total = 1000
    avail = int(round(total * (1 - pct / 100.0)))
    return MemorySnapshot(timestamp=ts, total_kb=total, free_kb=0, available_kb=avail,
                          buffers_kb=0, cached_kb=0, swap_cached_kb=0)


def _battery(pct, ts=0.0):
    return BatterySnapshot(timestamp=ts, level_percent=pct, scale=100, voltage_mv=4000,
                           temperature_c=25.0, status=BatteryStatus.DISCHARGING, status_raw=3,
                           health=BatteryHealth.GOOD, health_raw=2, present=True,
                           ac_powered=False, usb_powered=False, wireless_powered=False,
                           technology="Li-ion", charge_counter=1000)


def _storage(pct, ts=0.0):
    total = 1000
    used = int(round(total * pct / 100.0))
    return StorageSnapshot(timestamp=ts, mount="/data", total_kb=total, used_kb=used,
                           available_kb=total - used)


def _processes(n, ts=0.0):
    return ProcessSnapshot(timestamp=ts, processes=list(range(n)))


def test_view_state_detects_cpu_pressure_and_correlates_app():
    orch = PerformanceOrchestrator()
    t = 0.0
    for i in range(25):
        t += 1.0
        orch.ingest(cpu=_cpu(20.0 + i % 3, t), memory=_mem(30.0, t), battery=_battery(80.0, t),
                    storage=_storage(40.0, t), processes=_processes(120, t), timestamp=t)
    for _ in range(8):
        t += 1.0
        orch.ingest(cpu=_cpu(96.0, t), memory=_mem(30.0, t), battery=_battery(80.0, t),
                    storage=_storage(40.0, t), processes=_processes(120, t), timestamp=t)
    snap = BackgroundAppsSnapshot(timestamp=t, entries=(
        BackgroundAppEntry(package_name="com.example.heavy", label="Heavy App", uid=10001,
                           pids=(1, 2), cpu_percent=40.0, memory_percent=20.0,
                           state=BackgroundAppState.BACKGROUND),))
    orch.set_background_apps(snap)
    state = orch.view_state()
    assert state.overall_state == "CPU_PRESSURE"
    assert state.metrics["cpu"].condition == "CRITICAL"
    assert state.findings[0].severity == "critical"
    assert state.app_correlations[0].package == "com.example.heavy"
    assert state.app_correlations[0].process_count == 2
    assert any(e.phase == "started" for e in state.events)


def _warmup_breach(orch, start_ts=0.0):
    """Feed a cool baseline then a sustained high CPU breach (>= 2 samples)."""
    t = start_ts
    for i in range(25):
        t += 1.0
        orch.ingest(cpu=_cpu(20.0 + i % 3, t), memory=_mem(30.0, t), battery=_battery(80.0, t),
                    storage=_storage(40.0, t), processes=_processes(120, t), timestamp=t)
    for _ in range(3):
        t += 1.0
        orch.ingest(cpu=_cpu(96.0, t), memory=_mem(30.0, t), battery=_battery(80.0, t),
                    storage=_storage(40.0, t), processes=_processes(120, t), timestamp=t)
    return t


def test_events_accumulate_across_steady_state_ticks():
    orch = PerformanceOrchestrator()
    _warmup_breach(orch)
    assert any(e.phase == "started" for e in orch.view_state().events)
    # Many steady-state ticks with no transition must not erase the event.
    t = 30.0
    for _ in range(2, 12):
        t += 1.0
        orch.ingest(cpu=_cpu(96.0, t), memory=_mem(30.0, t), battery=_battery(80.0, t),
                    storage=_storage(40.0, t), processes=_processes(120, t), timestamp=t)
    assert any(e.phase == "started" for e in orch.view_state().events)


def test_end_session_clears_view_state():
    orch = PerformanceOrchestrator()
    _warmup_breach(orch)
    assert orch.view_state().events
    orch.end_session()
    state = orch.view_state()
    assert state.events == ()
    assert state.app_correlations == ()
