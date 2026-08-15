"""Fixture factories for the investigation-core tests.

Mirrors ``incident_fixtures``: no device required, everything is pure
in-memory scenario data. Factories cover the baseline identity models,
the monitor's process/socket snapshots, the heuristic models and the
Session type the investigation aggregations consume.
"""

from __future__ import annotations

from datetime import datetime, timezone

from android_task_manager.baseline.export import Session
from android_task_manager.baseline.models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
    CHANGE_REMOVED,
    SEVERITY_INFO,
    BaselineSnapshot,
    DriftEvent,
    DriftReport,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from android_task_manager.heuristics.models import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    HeuristicReport,
    SuspiciousSignal,
)
from android_task_manager.network_investigation.models import (
    NetworkInvestigationSnapshot,
    SocketInfo,
)
from android_task_manager.process.models import (
    ProcessCategory,
    ProcessInfo,
    ProcessSnapshot,
)
from android_task_manager.investigation.models import (
    EVENT_BASELINE_CREATED,
    EVENT_DRIFT_EVENT,
    EVENT_SIGNAL_GENERATED,
    EvidenceExplanation,
    EvidenceFact,
    InvestigationEvent,
    SnapshotCompleteness,
    Observation,
)


def ts(value: str) -> datetime:
    """Parse an ISO timestamp in UTC (test helper for determinism)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def process(
    uid: int | None,
    name: str,
    category: ProcessCategory = ProcessCategory.USER,
) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=category)


def package(name: str, uid: int | None = None) -> PackageIdentity:
    return PackageIdentity(package_name=name, uid=uid)


def socket(
    protocol: str,
    address: str,
    port: int,
    uid: int | None = None,
) -> SocketIdentity:
    return SocketIdentity(
        protocol=protocol, local_address=address, local_port=port, uid=uid
    )


def snapshot(
    created_at: datetime,
    processes: tuple[ProcessRef, ...] = (),
    packages: tuple[PackageIdentity, ...] = (),
    sockets: tuple[SocketIdentity, ...] = (),
    *,
    processes_verified: bool = True,
    packages_verified: bool = True,
    sockets_verified: bool = True,
    serial: str = "TEST-1",
) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=created_at,
        device_serial=serial,
        processes=frozenset(processes),
        packages=frozenset(packages),
        sockets=frozenset(sockets),
        processes_verified=processes_verified,
        packages_verified=packages_verified,
        sockets_verified=sockets_verified,
    )


def drift_event(
    category: str,
    change_type: str,
    entity: str,
    explanation: str = "",
) -> DriftEvent:
    return DriftEvent(
        category=category,
        change_type=change_type,
        severity=SEVERITY_INFO,
        entity=entity,
        explanation=explanation,
    )


def drift_report(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    events: tuple[DriftEvent, ...] = (),
    *,
    compared_at: datetime | None = None,
    unverified_categories: tuple[str, ...] = (),
) -> DriftReport:
    return DriftReport(
        baseline_created_at=baseline.created_at,
        compared_at=compared_at or current.created_at,
        events=events,
        unverified_categories=unverified_categories,
    )


def make_session(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    events: tuple[DriftEvent, ...] = (),
) -> Session:
    return Session(
        baseline=baseline,
        current=current,
        drift_report=drift_report(baseline, current, events),
    )


def obs(
    completeness: SnapshotCompleteness,
    identities: tuple,
    timestamp: float = 0.0,
) -> Observation:
    return Observation(
        completeness=completeness,
        identities=frozenset(identities),
        timestamp=timestamp,
    )


def process_info(
    pid: int,
    name: str,
    uid: int | None,
    *,
    ppid: int | None = None,
    category: ProcessCategory = ProcessCategory.USER,
    cpu_percent: float | None = None,
    memory_percent: float | None = None,
    state: str | None = None,
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=uid,
        state=state,
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        category=category,
        ppid=ppid,
    )


def process_snapshot(
    timestamp: float,
    infos: tuple[ProcessInfo, ...],
) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=timestamp, processes=list(infos))


def socket_info(
    protocol: str,
    address: str,
    port: int,
    *,
    family: str = "inet",
    remote_address: str | None = None,
    remote_port: int | None = None,
    state: str | None = None,
    uid: int | None = None,
    pid: int | None = None,
) -> SocketInfo:
    return SocketInfo(
        protocol=protocol,
        family=family,
        local_address=address,
        local_port=port,
        remote_address=remote_address,
        remote_port=remote_port,
        state=state,
        uid=uid,
        pid=pid,
    )


def network_snapshot(
    timestamp: float,
    sockets: tuple[SocketInfo, ...] = (),
    *,
    source_available: bool = True,
    uid_packages: dict[int, tuple[str, ...]] | None = None,
) -> NetworkInvestigationSnapshot:
    return NetworkInvestigationSnapshot(
        timestamp=timestamp,
        sockets=sockets,
        source_available=source_available,
        uid_packages=uid_packages or {},
    )


def signal(
    rule_id: str,
    severity: str,
    entity: str,
    reason: str = "Test reason.",
    contributing_events: tuple[str, ...] = (),
) -> SuspiciousSignal:
    return SuspiciousSignal(
        rule_id=rule_id,
        severity=severity,
        entity=entity,
        reason=reason,
        contributing_events=contributing_events,
    )


def heuristic_report(
    rules: tuple[str, ...],
    signals: tuple[SuspiciousSignal, ...],
    evaluated_at: datetime,
) -> HeuristicReport:
    return HeuristicReport(
        rules_applied=rules,
        signals=signals,
        evaluated_at=evaluated_at,
    )


def facts() -> tuple[EvidenceFact, ...]:
    """A small deterministic evidence-fact set for GUI/dialog tests."""
    return (
        EvidenceFact("PROCESS", "Process: com.example.app.", "com.example.app"),
        EvidenceFact("NETWORK", "Socket state: LISTEN.", "tcp:0.0.0.0:4444"),
        EvidenceFact("BASELINE", "Was not present in baseline.", "com.example.app"),
    )


def explanation(
    headline: str,
    sig: SuspiciousSignal | None = None,
    facts: tuple[EvidenceFact, ...] = (),
) -> EvidenceExplanation:
    return EvidenceExplanation(
        signal=sig or signal("SAMPLE", "MEDIUM", "sample.entity"),
        headline=headline,
        facts=facts,
    )


def timeline_events() -> tuple[InvestigationEvent, ...]:
    """A deterministic, fully-populated timeline for dialog tests."""
    at = ts("2026-01-01T10:00:00Z")
    return (
        InvestigationEvent(
            event_id="T-001",
            event_type=EVENT_BASELINE_CREATED,
            title="Baseline created",
            description="Baseline captured.",
            timestamp=at,
            severity=None,
        ),
        InvestigationEvent(
            event_id="T-002",
            event_type=EVENT_DRIFT_EVENT,
            title="process NEW",
            description="New process.",
            timestamp=ts("2026-01-01T10:00:05Z"),
            entity="com.example.app",
            evidence_refs=("E-001",),
            related_entities=("com.example.app",),
        ),
        InvestigationEvent(
            event_id="T-003",
            event_type=EVENT_SIGNAL_GENERATED,
            title="NEW_PROCESS_WITH_ACTIVE_SOCKET",
            description="Signal.",
            timestamp=ts("2026-01-01T10:00:06Z"),
            severity=SEVERITY_MEDIUM,
            entity="com.example.app",
            evidence_refs=("tcp:0.0.0.0:4444",),
        ),
    )


# ---------------------------------------------------------------------------
# Stability scenarios (identity drift + observation series)
# ---------------------------------------------------------------------------

#: Baseline with one stable system process and one app process.
STABLE_A = process(1000, "system_server", ProcessCategory.SYSTEM)
STABLE_APP = process(10100, "com.example.stable", ProcessCategory.USER)
#: The new process seen in drift scenarios.
NEW_PROC = process(10200, "com.example.newproc", ProcessCategory.USER)
NEW_SOCK = socket("tcp", "0.0.0.0", 4444, uid=10200)
STABLE_SOCK = socket("tcp", "0.0.0.0", 5353, uid=10100)


def baseline_with_stable() -> BaselineSnapshot:
    return snapshot(
        ts("2026-01-01T10:00:00Z"),
        processes=(STABLE_A, STABLE_APP),
        sockets=(STABLE_SOCK,),
    )


def current_with_new_process() -> BaselineSnapshot:
    return snapshot(
        ts("2026-01-01T10:00:05Z"),
        processes=(STABLE_A, STABLE_APP, NEW_PROC),
        sockets=(STABLE_SOCK,),
    )


def new_process_report() -> DriftReport:
    baseline = baseline_with_stable()
    current = current_with_new_process()
    return drift_report(
        baseline,
        current,
        events=(drift_event(CATEGORY_PROCESS, CHANGE_NEW, NEW_PROC.process_name),),
    )


def new_socket_report() -> DriftReport:
    baseline = baseline_with_stable()
    current = snapshot(
        ts("2026-01-01T10:00:05Z"),
        processes=(STABLE_A, STABLE_APP),
        sockets=(STABLE_SOCK, NEW_SOCK),
    )
    return drift_report(
        baseline,
        current,
        events=(
            drift_event(
                CATEGORY_SOCKET,
                CHANGE_NEW,
                "tcp:0.0.0.0:4444",
            ),
        ),
    )


def removed_process_report() -> DriftReport:
    baseline = baseline_with_stable()
    current = snapshot(
        ts("2026-01-01T10:00:05Z"),
        processes=(STABLE_A,),
        sockets=(STABLE_SOCK,),
    )
    return drift_report(
        baseline,
        current,
        events=(
            drift_event(
                CATEGORY_PROCESS,
                CHANGE_REMOVED,
                STABLE_APP.process_name,
            ),
        ),
    )


#: Process observations for the "new process appears and persists" story.
def persistent_series() -> dict[str, tuple[Observation, ...]]:
    return {
        CATEGORY_PROCESS: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP, NEW_PROC), 101.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP, NEW_PROC), 102.0),
        ),
        CATEGORY_SOCKET: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 101.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 102.0),
        ),
    }


def transient_series() -> dict[str, tuple[Observation, ...]]:
    """The new process was seen once, then was gone again."""
    return {
        CATEGORY_PROCESS: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP, NEW_PROC), 101.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 102.0),
        ),
        CATEGORY_SOCKET: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 101.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 102.0),
        ),
    }


def uncertain_series() -> dict[str, tuple[Observation, ...]]:
    """The drift-check read was PARTIAL: absence cannot be confirmed."""
    return {
        CATEGORY_PROCESS: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 101.0),
            obs(SnapshotCompleteness.PARTIAL, (STABLE_A,), 102.0),
        ),
        CATEGORY_SOCKET: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 101.0),
            obs(SnapshotCompleteness.PARTIAL, (), 102.0),
        ),
    }


def failed_series() -> dict[str, tuple[Observation, ...]]:
    """The latest read FAILED outright: no claim either way."""
    return {
        CATEGORY_PROCESS: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 101.0),
            obs(SnapshotCompleteness.FAILED, (), 102.0),
        ),
        CATEGORY_SOCKET: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 101.0),
            obs(SnapshotCompleteness.FAILED, (), 102.0),
        ),
    }


def confirmed_removal_series() -> dict[str, tuple[Observation, ...]]:
    """Two consecutive COMPLETE reads without the app: REMOVED."""
    return {
        CATEGORY_PROCESS: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A,), 101.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A,), 102.0),
        ),
        CATEGORY_SOCKET: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 101.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 102.0),
        ),
    }


def single_absence_series() -> dict[str, tuple[Observation, ...]]:
    """Only one COMPLETE absence: not yet confirmed as REMOVED."""
    return {
        CATEGORY_PROCESS: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A, STABLE_APP), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_A,), 101.0),
        ),
        CATEGORY_SOCKET: (
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 100.0),
            obs(SnapshotCompleteness.COMPLETE, (STABLE_SOCK,), 101.0),
        ),
    }


def package_pass_through_report() -> DriftReport:
    baseline = baseline_with_stable()
    current = snapshot(
        ts("2026-01-01T10:00:05Z"),
        processes=(STABLE_A, STABLE_APP),
        packages=(package("com.example.newpkg", 10500),),
        sockets=(STABLE_SOCK,),
    )
    return drift_report(
        baseline,
        current,
        events=(
            drift_event(CATEGORY_PACKAGE, CHANGE_NEW, "com.example.newpkg"),
        ),
    )


# ---------------------------------------------------------------------------
# Process-tree fixture (Vivo-style hierarchy)
# ---------------------------------------------------------------------------

def tree_snapshot() -> ProcessSnapshot:
    return process_snapshot(
        1000.0,
        (
            process_info(1, "init", 0, ppid=0, category=ProcessCategory.SYSTEM),
            process_info(2, "kthreadd", 0, ppid=0, category=ProcessCategory.KERNEL_THREAD),
            process_info(754, "system_server", 1000, ppid=1, category=ProcessCategory.SYSTEM),
            process_info(18472, "com.example.app", 10200, ppid=754, category=ProcessCategory.USER),
            process_info(18491, "com.example.app:service", 10200, ppid=18472, category=ProcessCategory.USER),
            process_info(18493, "com.example.app:renderer", 10200, ppid=18472, category=ProcessCategory.USER),
            process_info(90001, "orphan.process", 10999, ppid=99999, category=ProcessCategory.USER),
        ),
    )