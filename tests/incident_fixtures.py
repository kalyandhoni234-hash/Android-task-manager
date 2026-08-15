"""Shared fixture factories and scenarios for the incident-report tests.

All data is synthetic and in-memory — no device, no network. Scenarios
follow the task's fixture list:

* A — normal device (no drift)
* B — new process
* C — new package
* D — new listening socket
* E — HIGH suspicious signal
* F — permission finding
* G — multiple correlated findings
* H — unavailable data (None uids, unverified categories, 0.0 metrics)
* I — empty session
* J — mixed HIGH/MEDIUM/INFO findings

Each scenario exposes the exact inputs ``build_incident_report`` consumes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from android_task_manager.baseline.export import Session
from android_task_manager.baseline.models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
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
from android_task_manager.permissions.models import (
    CombinationFlag,
    PackagePermissionAudit,
    PermissionEntry,
)
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot

BASELINE_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
COMPARED_AT = datetime(2026, 8, 15, 12, 30, 0, tzinfo=timezone.utc)
EVALUATED_AT = datetime(2026, 8, 15, 12, 31, 0, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 8, 15, 12, 40, 0, tzinfo=timezone.utc)
AUDIT_AT = datetime(2026, 8, 15, 12, 45, 0, tzinfo=timezone.utc)

SERIAL = "R58M1234567"


def proc(
    name: str,
    uid: int | None = 10200,
    category: ProcessCategory = ProcessCategory.USER,
) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=category)


def pkg(name: str, uid: int | None = 10200) -> PackageIdentity:
    return PackageIdentity(package_name=name, uid=uid)


def sock(protocol: str, address: str, port: int, uid: int | None = 10200) -> SocketIdentity:
    return SocketIdentity(protocol=protocol, local_address=address, local_port=port, uid=uid)


def snapshot(
    *,
    processes: frozenset[ProcessRef] = frozenset(),
    packages: frozenset[PackageIdentity] = frozenset(),
    sockets: frozenset[SocketIdentity] = frozenset(),
    created_at: datetime = BASELINE_AT,
    processes_verified: bool = True,
    packages_verified: bool = True,
    sockets_verified: bool = True,
) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=created_at,
        device_serial=SERIAL,
        processes=processes,
        packages=packages,
        sockets=sockets,
        processes_verified=processes_verified,
        packages_verified=packages_verified,
        sockets_verified=sockets_verified,
    )


def session(
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    *,
    events: tuple[DriftEvent, ...] = (),
    unverified: tuple[str, ...] = (),
    compared_at: datetime = COMPARED_AT,
) -> Session:
    return Session(
        baseline=baseline,
        current=current,
        drift_report=DriftReport(
            baseline_created_at=baseline.created_at,
            compared_at=compared_at,
            events=events,
            unverified_categories=unverified,
        ),
    )


def new_event(category: str, entity: str) -> DriftEvent:
    return DriftEvent(category=category, change_type=CHANGE_NEW, entity=entity)


def signal(
    rule_id: str,
    severity: str,
    entity: str,
    reason: str,
    contributing: tuple[str, ...] = (),
) -> SuspiciousSignal:
    return SuspiciousSignal(
        rule_id=rule_id,
        severity=severity,
        entity=entity,
        reason=reason,
        contributing_events=contributing,
    )


def heuristics(
    *signals: SuspiciousSignal,
    evaluated_at: datetime = EVALUATED_AT,
    rules: tuple[str, ...] = ("RULE_A", "RULE_B", "RULE_C"),
) -> HeuristicReport:
    return HeuristicReport(evaluated_at=evaluated_at, signals=signals, rules_applied=rules)


def entry(name: str, granted: bool | None = True, permission_type: str = "runtime") -> PermissionEntry:
    return PermissionEntry(name=name, granted=granted, permission_type=permission_type)


def audit(
    package_name: str,
    permissions: tuple[PermissionEntry, ...] = (),
    flags: tuple[CombinationFlag, ...] = (),
    read_at: datetime = AUDIT_AT,
    parse_complete: bool = True,
) -> PackagePermissionAudit:
    return PackagePermissionAudit(
        package_name=package_name,
        read_at=read_at,
        permissions=permissions,
        parse_complete=parse_complete,
        combination_flags=flags,
    )


def network_snapshot(
    sockets: tuple[SocketInfo, ...] = (),
    uid_packages: dict[int, tuple[str, ...]] | None = None,
) -> NetworkInvestigationSnapshot:
    return NetworkInvestigationSnapshot(
        timestamp=0.0,
        sockets=sockets,
        source_available=True,
        uid_packages=uid_packages or {},
    )


def process_snapshot(*infos: ProcessInfo, timestamp: float = 0.0) -> ProcessSnapshot:
    return ProcessSnapshot(timestamp=timestamp, processes=list(infos))


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_a_normal() -> dict:
    """Normal device: no drift, heuristics evaluated with no signals."""
    base = snapshot(
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
        packages=frozenset({pkg("com.example.app", 10200)}),
        sockets=frozenset({sock("tcp", "0.0.0.0", 8080, 10200)}),
    )
    return {
        "session": session(base, base),
        "heuristics": heuristics(),
        "generated_at": GENERATED_AT,
    }


def scenario_b_new_process() -> dict:
    """Scenario B — a new process appears (facts only, no signal)."""
    base = snapshot(
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
        packages=frozenset({pkg("com.example.app", 10200)}),
    )
    current = snapshot(
        processes=frozenset(
            {
                proc("system_server", 1000, ProcessCategory.SYSTEM),
                proc("com.example.daemon", 10210, ProcessCategory.USER),
            }
        ),
        packages=frozenset({pkg("com.example.app", 10200)}),
        created_at=COMPARED_AT,
    )
    return {
        "session": session(
            base, current, events=(new_event(CATEGORY_PROCESS, "com.example.daemon"),)
        ),
        "heuristics": heuristics(),
        "generated_at": GENERATED_AT,
    }


def scenario_c_new_package() -> dict:
    """Scenario C — a new package appears (facts only, no signal)."""
    base = snapshot(
        packages=frozenset({pkg("com.example.app", 10200)}),
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
    )
    current = snapshot(
        packages=frozenset(
            {pkg("com.example.app", 10200), pkg("com.example.installed", 10230)}
        ),
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
        created_at=COMPARED_AT,
    )
    return {
        "session": session(
            base, current, events=(new_event(CATEGORY_PACKAGE, "com.example.installed"),)
        ),
        "heuristics": heuristics(),
        "generated_at": GENERATED_AT,
    }


def scenario_d_new_socket() -> dict:
    """Scenario D — a new listening socket appears (facts only, no signal)."""
    base = snapshot(
        sockets=frozenset({sock("tcp", "0.0.0.0", 8080, 10200)}),
        packages=frozenset({pkg("com.example.app", 10200)}),
    )
    current = snapshot(
        sockets=frozenset(
            {sock("tcp", "0.0.0.0", 8080, 10200), sock("tcp", "0.0.0.0", 4444, 10210)}
        ),
        packages=frozenset({pkg("com.example.app", 10200), pkg("com.example.other", 10210)}),
        created_at=COMPARED_AT,
    )
    return {
        "session": session(
            base, current, events=(new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:4444"),)
        ),
        "heuristics": heuristics(),
        "network_investigation": network_snapshot(
            sockets=(
                SocketInfo(
                    protocol="tcp", family="inet", local_address="0.0.0.0",
                    local_port=4444, remote_address="0.0.0.0", remote_port=0,
                    state="LISTEN", uid=10210, inode=12345,
                ),
            ),
            uid_packages={10210: ("com.example.other",)},
        ),
        "generated_at": GENERATED_AT,
    }


def scenario_e_high_signal() -> dict:
    """Scenario E — a HIGH suspicious signal (multiple new listening sockets)."""
    base = snapshot(
        sockets=frozenset({sock("tcp", "0.0.0.0", 8080, 1000)}),
        packages=frozenset({pkg("com.android.systemui", 1000)}),
    )
    current = snapshot(
        sockets=frozenset(
            {
                sock("tcp", "0.0.0.0", 8080, 1000),
                sock("tcp", "0.0.0.0", 4444, 10200),
                sock("tcp", "0.0.0.0", 5555, 10200),
            }
        ),
        packages=frozenset({pkg("com.android.systemui", 1000)}),
        created_at=COMPARED_AT,
    )
    drift = session(
        base,
        current,
        events=(
            new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:4444"),
            new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:5555"),
        ),
    )
    high = signal(
        "MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS",
        SEVERITY_HIGH,
        "uid=10200",
        "Uid 10200 opened 2 new listening sockets in a single check — "
        "unusual for most apps and worth investigating.",
        contributing=("tcp:0.0.0.0:4444", "tcp:0.0.0.0:5555"),
    )
    return {
        "session": drift,
        "heuristics": heuristics(high),
        "generated_at": GENERATED_AT,
    }


def scenario_f_permission_finding() -> dict:
    """Scenario F — a permission audit with a combination flag (INFO)."""
    base = snapshot(
        packages=frozenset({pkg("com.example.smsapp", 10200)}),
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
    )
    flags = (
        CombinationFlag(
            flag_id="SMS_ACCESSIBILITY_DEVICE_ADMIN",
            matched_permissions=(
                "android.permission.BIND_ACCESSIBILITY_SERVICE",
                "android.permission.BIND_DEVICE_ADMIN",
                "android.permission.READ_SMS",
            ),
            description=(
                "Requests SMS access alongside Accessibility Service and Device Admin — a "
                "combination sometimes seen in banking-trojan-style malware, worth reviewing "
                "why this app needs all three."
            ),
        ),
    )
    audits = (
        audit(
            "com.example.smsapp",
            permissions=(
                entry("android.permission.INTERNET"),
                entry("android.permission.READ_SMS"),
                entry("android.permission.RECEIVE_SMS", granted=False),
                entry("android.permission.VIBRATE", granted=True, permission_type="install"),
            ),
            flags=flags,
        ),
    )
    return {
        "session": session(base, base),
        "heuristics": heuristics(),
        "permission_audits": audits,
        "generated_at": GENERATED_AT,
    }


def scenario_g_correlated() -> dict:
    """Scenario G — correlated findings: new package + new process + new
    sockets sharing one UID; all three rules fire (HIGH + 2 MEDIUM)."""
    base = snapshot(
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
        packages=frozenset({pkg("com.android.systemui", 1000)}),
        sockets=frozenset({sock("tcp", "0.0.0.0", 8080, 1000)}),
    )
    current = snapshot(
        processes=frozenset(
            {
                proc("system_server", 1000, ProcessCategory.SYSTEM),
                proc("com.example.newapp", 10250, ProcessCategory.USER),
            }
        ),
        packages=frozenset(
            {pkg("com.android.systemui", 1000), pkg("com.example.newapp", 10250)}
        ),
        sockets=frozenset(
            {
                sock("tcp", "0.0.0.0", 8080, 1000),
                sock("tcp", "0.0.0.0", 4444, 10250),
                sock("tcp", "0.0.0.0", 5555, 10250),
            }
        ),
        created_at=COMPARED_AT,
    )
    drift = session(
        base,
        current,
        events=(
            new_event(CATEGORY_PACKAGE, "com.example.newapp"),
            new_event(CATEGORY_PROCESS, "com.example.newapp"),
            new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:4444"),
            new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:5555"),
        ),
    )
    signals = (
        signal(
            "MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS",
            SEVERITY_HIGH,
            "uid=10250",
            "Uid 10250 opened 2 new listening sockets in a single check.",
            contributing=("tcp:0.0.0.0:4444", "tcp:0.0.0.0:5555"),
        ),
        signal(
            "NEW_PROCESS_WITH_ACTIVE_SOCKET",
            SEVERITY_MEDIUM,
            "com.example.newapp",
            "New process 'com.example.newapp' appeared alongside 2 new network "
            "sockets owned by the same UID (10250).",
            contributing=("com.example.newapp", "tcp:0.0.0.0:4444", "tcp:0.0.0.0:5555"),
        ),
        signal(
            "NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS",
            SEVERITY_MEDIUM,
            "com.example.newapp",
            "A newly installed package 'com.example.newapp' immediately has a "
            "running user process.",
            contributing=("com.example.newapp",),
        ),
    )
    return {
        "session": drift,
"heuristics": heuristics(*signals),
        "network_investigation": network_snapshot(
            sockets=(
                SocketInfo(
                    protocol="tcp", family="inet", local_address="0.0.0.0",
                    local_port=4444, state="LISTEN", uid=10250,
                ),
                SocketInfo(
                    protocol="tcp", family="inet", local_address="0.0.0.0",
                    local_port=5555, state="LISTEN", uid=10250,
                ),
            ),
            uid_packages={10250: ("com.example.newapp",)},
        ),
        "process_snapshot": process_snapshot(
            ProcessInfo(
                pid=18472, name="com.example.newapp", uid=10250, state="S",
                cpu_percent=12.5, memory_percent=3.0, category=ProcessCategory.USER,
            ),
        ),
        "generated_at": GENERATED_AT,
    }


def scenario_h_unavailable() -> dict:
    """Scenario H — unavailable data stays unavailable: None uids, unverified
    socket category, a process with 0.0 metrics (zero is not unavailable)."""
    base = snapshot(
        processes=frozenset({proc("orphan", None, ProcessCategory.USER)}),
        packages=frozenset({pkg("com.example.nouid", None)}),
        sockets=frozenset(),
        sockets_verified=True,
    )
    current = snapshot(
        processes=frozenset({proc("orphan", None, ProcessCategory.USER)}),
        packages=frozenset({pkg("com.example.nouid", None)}),
        sockets=frozenset(),
        sockets_verified=False,
        created_at=COMPARED_AT,
    )
    drift = session(
        base,
        current,
        events=(new_event(CATEGORY_PROCESS, "orphan"),),
        unverified=(CATEGORY_SOCKET,),
    )
    return {
        "session": drift,
        "heuristics": heuristics(),
        "process_snapshot": process_snapshot(
            ProcessInfo(
                pid=999, name="orphan", uid=None, state="S",
                cpu_percent=0.0, memory_percent=0.0, category=ProcessCategory.USER,
            ),
        ),
        "generated_at": GENERATED_AT,
    }


def scenario_i_empty() -> dict:
    """Scenario I — empty session: identical empty snapshots."""
    base = snapshot()
    return {
        "session": session(base, base),
        "heuristics": heuristics(),
        "generated_at": GENERATED_AT,
    }


def scenario_j_mixed() -> dict:
    """Scenario J — mixed HIGH/MEDIUM/INFO findings in one report."""
    base = snapshot(
        processes=frozenset({proc("system_server", 1000, ProcessCategory.SYSTEM)}),
        packages=frozenset({pkg("com.android.systemui", 1000)}),
        sockets=frozenset({sock("tcp", "0.0.0.0", 8080, 1000)}),
    )
    current = snapshot(
        processes=frozenset(
            {
                proc("system_server", 1000, ProcessCategory.SYSTEM),
                proc("com.example.probe", 10270, ProcessCategory.USER),
            }
        ),
        packages=frozenset(
            {pkg("com.android.systemui", 1000), pkg("com.example.flagpkg", 10280)}
        ),
        sockets=frozenset(
            {
                sock("tcp", "0.0.0.0", 8080, 1000),
                sock("tcp", "0.0.0.0", 6666, 10270),
                sock("tcp", "0.0.0.0", 7777, 10270),
            }
        ),
        created_at=COMPARED_AT,
    )
    drift = session(
        base,
        current,
        events=(
            new_event(CATEGORY_PROCESS, "com.example.probe"),
            new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:6666"),
            new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:7777"),
            new_event(CATEGORY_PACKAGE, "com.example.flagpkg"),
        ),
    )
    high = signal(
        "MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS",
        SEVERITY_HIGH,
        "uid=10270",
        "Uid 10270 opened 2 new listening sockets in a single check.",
        contributing=("tcp:0.0.0.0:6666", "tcp:0.0.0.0:7777"),
    )
    medium = signal(
        "NEW_PROCESS_WITH_ACTIVE_SOCKET",
        SEVERITY_MEDIUM,
        "com.example.probe",
        "New process 'com.example.probe' appeared alongside 2 new network "
        "sockets owned by the same UID (10270).",
        contributing=("com.example.probe", "tcp:0.0.0.0:6666", "tcp:0.0.0.0:7777"),
    )
    flags = (
        CombinationFlag(
            flag_id="OVERLAY_ACCESSIBILITY",
            matched_permissions=(
                "android.permission.BIND_ACCESSIBILITY_SERVICE",
                "android.permission.SYSTEM_ALERT_WINDOW",
            ),
            description="Requests draw-over-other-apps alongside Accessibility "
            "Service — this combination can enable overlay-based "
            "phishing/credential-capture UI, worth reviewing.",
        ),
    )
    audits = (
        audit(
            "com.example.flagpkg",
            permissions=(
                entry("android.permission.SYSTEM_ALERT_WINDOW"),
                entry("android.permission.BIND_ACCESSIBILITY_SERVICE"),
            ),
            flags=flags,
        ),
    )
    return {
        "session": drift,
        "heuristics": heuristics(high, medium),
        "permission_audits": audits,
        "generated_at": GENERATED_AT,
    }


ALL_SCENARIOS = {
    "a": scenario_a_normal,
    "b": scenario_b_new_process,
    "c": scenario_c_new_package,
    "d": scenario_d_new_socket,
    "e": scenario_e_high_signal,
    "f": scenario_f_permission_finding,
    "g": scenario_g_correlated,
    "h": scenario_h_unavailable,
    "i": scenario_i_empty,
    "j": scenario_j_mixed,
}


def build_for(scenario: str):
    """Convenience: run a scenario through the report builder."""
    from android_task_manager.incident.builder import build_incident_report

    inputs = ALL_SCENARIOS[scenario]()
    return build_incident_report(**inputs)