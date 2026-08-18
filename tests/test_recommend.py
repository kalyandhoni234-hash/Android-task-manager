"""Tests for the recommendation engine (Phase E).

Covers the observation → finding → recommendation → action chain:
deterministic mapping from health findings, validated package targets,
never-automation-ready destructive actions, deduplication, deterministic
ordering, and the unavailable-data-never-recommends invariant.
"""

from __future__ import annotations

import dataclasses

import pytest

from android_task_manager.action.capability import FORCE_STOP
from android_task_manager.health.models import (
    COMPONENT_APPLICATIONS,
    COMPONENT_BATTERY,
    COMPONENT_CONNECTIVITY,
    COMPONENT_CPU,
    COMPONENT_MEMORY,
    COMPONENT_PROCESSES,
    COMPONENT_STORAGE,
    ComponentHealth,
    DeviceHealth,
    Finding,
    HealthSeverity,
    HealthStatus,
)
from android_task_manager.process.models import ProcessInfo, ProcessSnapshot
from android_task_manager.recommend import is_valid_package_name, recommend
from android_task_manager.thresholds import CPU_HIGH_PERCENT, MEMORY_USED_HIGH_PERCENT


def _health_with(*findings: Finding) -> DeviceHealth:
    components = {
        component: ComponentHealth(
            component=component,
            status=HealthStatus.HEALTHY,
            score=100,
            value=None,
            findings=tuple(
                f for f in findings if f.component == component
            ),
        )
        for component in (
            COMPONENT_CPU,
            COMPONENT_MEMORY,
            COMPONENT_BATTERY,
            COMPONENT_STORAGE,
            COMPONENT_PROCESSES,
            COMPONENT_APPLICATIONS,
            COMPONENT_CONNECTIVITY,
        )
    }
    return DeviceHealth(
        overall_score=70.0,
        status=HealthStatus.WARNING,
        components=components,
        findings=list(findings),
        evaluated_at=100.0,
        device_serial="FAKE123",
    )


def _finding(component: str, severity: HealthSeverity = HealthSeverity.WARNING) -> Finding:
    return Finding(
        severity=severity,
        component=component,
        title=f"{component} finding",
        explanation="explanation",
        evidence=f"{component} evidence",
        recommendation="recommendation text",
        timestamp=100.0,
    )


def _user_process(name: str, cpu: float, memory: float = 5.0, pid: int = 8150) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=10001,
        state="R",
        cpu_percent=cpu,
        memory_percent=memory,
        category="user",
    )


# ---------------------------------------------------------------------------
# Package validation (Phase M hardening, used by recommendation targets)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "com.example.app",
        "org.android.chrome",
        "com.a.b.c",
        "com.example_app",
        "COM.EXAMPLE",
    ],
)
def test_valid_package_names(name: str) -> None:
    assert is_valid_package_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "com",
        "com.",
        ".com.example",
        "com/example",
        "com example",
        "com;rm -rf",
        "com$(id)",
        "com`id`",
        "com&id",
        "1com.example",
        "com.example_app.1",
    ],
)
def test_invalid_package_names_rejected(name: str) -> None:
    assert not is_valid_package_name(name)


# ---------------------------------------------------------------------------
# CPU findings
# ---------------------------------------------------------------------------


def test_cpu_finding_produces_informational_recommendation() -> None:
    health = _health_with(_finding(COMPONENT_CPU, HealthSeverity.CRITICAL))
    (rec,) = recommend(health)
    assert rec.finding_ref == "cpu finding"
    assert rec.action is None
    assert rec.severity == "critical"
    assert not rec.destructive
    assert not rec.automation_allowed
    assert rec.recommendation_id == "REC-001"


def test_cpu_finding_targets_heavy_user_process() -> None:
    health = _health_with(_finding(COMPONENT_CPU, HealthSeverity.CRITICAL))
    processes = ProcessSnapshot(
        timestamp=100.0,
        processes=[_user_process("com.example.app", CPU_HIGH_PERCENT)],
    )
    recs = recommend(health, processes)
    targeted = [r for r in recs if r.action == FORCE_STOP]
    assert len(targeted) == 1
    assert targeted[0].target == "com.example.app"
    assert targeted[0].destructive
    assert not targeted[0].automation_allowed
    assert "CPU 85%" in targeted[0].rationale


def test_cpu_finding_ignores_system_and_kernel_processes() -> None:
    health = _health_with(_finding(COMPONENT_CPU))
    system = _user_process("system_server", CPU_HIGH_PERCENT)
    system = ProcessInfo(
        pid=1054, name="system_server", uid=1000, state="R",
        cpu_percent=CPU_HIGH_PERCENT, memory_percent=1.0, category="system",
    )
    kernel = ProcessInfo(
        pid=17, name="kworker/0:1", uid=0, state="R",
        cpu_percent=CPU_HIGH_PERCENT, memory_percent=1.0, category="kernel",
    )
    processes = ProcessSnapshot(timestamp=100.0, processes=[system, kernel])
    recs = recommend(health, processes)
    assert all(r.action != FORCE_STOP for r in recs)


def test_cpu_finding_skips_non_package_process_names() -> None:
    health = _health_with(_finding(COMPONENT_CPU))
    weird = ProcessInfo(
        pid=9999, name="ro.target; rm -rf /", uid=10001, state="R",
        cpu_percent=CPU_HIGH_PERCENT, memory_percent=5.0, category="user",
    )
    processes = ProcessSnapshot(timestamp=100.0, processes=[weird])
    recs = recommend(health, processes)
    assert all(r.action != FORCE_STOP for r in recs)


# ---------------------------------------------------------------------------
# Process findings
# ---------------------------------------------------------------------------


def test_process_finding_targets_memory_hog() -> None:
    health = _health_with(_finding(COMPONENT_PROCESSES))
    processes = ProcessSnapshot(
        timestamp=100.0,
        processes=[_user_process("com.example.app", 5.0, MEMORY_USED_HIGH_PERCENT)],
    )
    recs = recommend(health, processes)
    targeted = [r for r in recs if r.action == FORCE_STOP]
    assert len(targeted) == 1
    assert targeted[0].target == "com.example.app"
    assert "RAM 90%" in targeted[0].rationale


def test_healthy_processes_produce_no_force_stop() -> None:
    health = _health_with(_finding(COMPONENT_PROCESSES))
    processes = ProcessSnapshot(
        timestamp=100.0,
        processes=[_user_process("com.example.app", 5.0, 10.0)],
    )
    recs = recommend(health, processes)
    assert all(r.action != FORCE_STOP for r in recs)


def test_same_target_never_recommended_twice() -> None:
    health = _health_with(
        _finding(COMPONENT_CPU, HealthSeverity.CRITICAL),
        _finding(COMPONENT_PROCESSES),
    )
    processes = ProcessSnapshot(
        timestamp=100.0,
        processes=[
            _user_process("com.example.app", CPU_HIGH_PERCENT, MEMORY_USED_HIGH_PERCENT),
            _user_process("com.example.other", CPU_HIGH_PERCENT),
        ],
    )
    recs = recommend(health, processes)
    targets = [r.target for r in recs if r.action == FORCE_STOP]
    assert targets.count("com.example.app") == 1
    assert targets.count("com.example.other") == 1


# ---------------------------------------------------------------------------
# Informational components
# ---------------------------------------------------------------------------


def test_memory_finding_is_informational() -> None:
    health = _health_with(_finding(COMPONENT_MEMORY, HealthSeverity.WARNING))
    (rec,) = recommend(health)
    assert rec.title == "Close heavy applications"
    assert rec.action is None
    assert rec.severity == "warning"


def test_battery_finding_uses_health_recommendation_text() -> None:
    health = _health_with(_finding(COMPONENT_BATTERY, HealthSeverity.CRITICAL))
    (rec,) = recommend(health)
    assert rec.title == "Act on the battery condition"
    assert rec.rationale == "recommendation text"
    assert rec.severity == "critical"


def test_storage_finding_is_informational() -> None:
    health = _health_with(_finding(COMPONENT_STORAGE))
    (rec,) = recommend(health)
    assert rec.title == "Free internal storage"
    assert rec.action is None


def test_connectivity_finding_is_informational() -> None:
    health = _health_with(_finding(COMPONENT_CONNECTIVITY))
    (rec,) = recommend(health)
    assert rec.title == "Check the network connection"
    assert rec.action is None


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def test_no_findings_produces_no_recommendations() -> None:
    health = _health_with()
    assert recommend(health) == ()


def test_unavailable_data_never_recommends() -> None:
    health = _health_with()
    processes = ProcessSnapshot(timestamp=100.0, processes=[])
    assert recommend(health, processes) == ()


def test_destructive_recommendations_never_automation_allowed() -> None:
    health = _health_with(_finding(COMPONENT_CPU, HealthSeverity.CRITICAL))
    processes = ProcessSnapshot(
        timestamp=100.0,
        processes=[_user_process("com.example.app", CPU_HIGH_PERCENT)],
    )
    for rec in recommend(health, processes):
        if rec.destructive:
            assert not rec.automation_allowed


def test_recommendations_are_deterministic() -> None:
    health = _health_with(
        _finding(COMPONENT_CPU, HealthSeverity.CRITICAL),
        _finding(COMPONENT_MEMORY, HealthSeverity.WARNING),
        _finding(COMPONENT_STORAGE, HealthSeverity.WARNING),
    )
    processes = ProcessSnapshot(
        timestamp=100.0,
        processes=[_user_process("com.example.app", CPU_HIGH_PERCENT)],
    )
    first = recommend(health, processes)
    second = recommend(health, processes)
    assert first == second


def test_critical_recommendations_come_first() -> None:
    health = _health_with(
        _finding(COMPONENT_MEMORY, HealthSeverity.WARNING),
        _finding(COMPONENT_CPU, HealthSeverity.CRITICAL),
    )
    recs = recommend(health)
    assert [r.severity for r in recs] == ["critical", "warning"]
    assert [r.recommendation_id for r in recs] == ["REC-001", "REC-002"]


def test_recommendation_types_are_frozen() -> None:
    health = _health_with(_finding(COMPONENT_CPU))
    (rec,) = recommend(health)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.title = "changed"
