"""Incident report builder — deterministic, GUI-independent aggregation.

``build_incident_report`` consumes the existing pipeline's structured
output (a :class:`Session`, an optional :class:`HeuristicReport`, optional
permission audits, and optional process/socket detail snapshots) and emits
one :class:`IncidentReport`. It is a pure function of its inputs:

* no I/O — no ADB, no shell, no network, no file writes;
* no GUI state — the same inputs always produce the same report content
  (timestamps are only those the inputs carry, plus ``generated_at`` which
  callers may pin for tests);
* deterministic ordering everywhere — findings, evidence rows, timeline
  events and recommendations are sorted with fixed keys, and ties are
  broken by type/id before content.

Every field of the report stays within the existing vocabulary: severities
are the existing ``HIGH``/``MEDIUM``/``INFO`` constants, drift wording is
the diff engine's own explanations, and heuristic findings preserve the
existing ``SuspiciousSignal`` reason verbatim.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .. import __version__
from ..baseline.export import Session
from ..baseline.models import (
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
from ..heuristics.models import HeuristicReport
from ..network_investigation.models import NetworkInvestigationSnapshot, SocketInfo
from ..permissions.models import PERMISSION_RUNTIME, PackagePermissionAudit
from ..process.models import ProcessSnapshot
from .models import (
    EVENT_BASELINE_CREATED,
    EVENT_DRIFT_CHECKED,
    EVENT_DRIFT_EVENT,
    EVENT_HEURISTICS_EVALUATED,
    EVENT_PERMISSION_AUDITED,
    EVENT_SIGNAL_GENERATED,
    FINDING_DRIFT,
    FINDING_PERMISSION_COMBINATION,
    FINDING_SUSPICIOUS_SIGNAL,
    SCHEMA_VERSION,
    SOURCE_MANUAL,
    STATUS_BASELINE,
    DeviceInfo,
    ExecutiveSummary,
    Finding,
    IncidentReport,
    IntegrityMetadata,
    NetworkEvidence,
    PackageEvidence,
    PermissionEvidence,
    ProcessEvidence,
    Recommendation,
    ReportMetadata,
    SeveritySummary,
    TimelineEvent,
)

#: Severity sort order used across the report (HIGH first).
_SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}

#: Fixed timeline type order, for deterministic ties on equal timestamps.
_TIMELINE_RANK = {
    EVENT_BASELINE_CREATED: 0,
    EVENT_DRIFT_EVENT: 1,
    EVENT_DRIFT_CHECKED: 2,
    EVENT_HEURISTICS_EVALUATED: 3,
    EVENT_SIGNAL_GENERATED: 4,
    EVENT_PERMISSION_AUDITED: 5,
}

#: Investigation recommendations per finding type/category/change — fixed
#: text, investigation-only verbs (verify / inspect / compare / confirm /
#: review / cross-check). Never remediation: nothing here tells the user to
#: uninstall, disable, kill or delete anything.
_RECOMMENDATIONS: dict[tuple[str, str | None, str | None], tuple[str, ...]] = {
    (FINDING_SUSPICIOUS_SIGNAL, None, None): (
        "Review the drift events referenced by this signal.",
    ),
    (FINDING_PERMISSION_COMBINATION, None, None): (
        "Review why this package requests the flagged permission combination.",
    ),
    (FINDING_DRIFT, CATEGORY_PROCESS, CHANGE_NEW): (
        "Verify whether this process is expected on the device.",
        "Inspect the process's network activity and package association.",
        "Compare the process against the established baseline.",
    ),
    (FINDING_DRIFT, CATEGORY_PROCESS, CHANGE_REMOVED): (
        "Confirm that the process's absence is expected.",
    ),
    (FINDING_DRIFT, CATEGORY_PACKAGE, CHANGE_NEW): (
        "Verify the installation source and expected ownership of this package.",
        "Review this package's requested permissions.",
        "Compare the package's activity against the established baseline.",
    ),
    (FINDING_DRIFT, CATEGORY_PACKAGE, CHANGE_REMOVED): (
        "Confirm that the package's absence is expected.",
    ),
    (FINDING_DRIFT, CATEGORY_SOCKET, CHANGE_NEW): (
        "Verify whether this listening port is expected.",
        "Inspect the owning process and package.",
        "Compare the socket against the established baseline.",
    ),
    (FINDING_DRIFT, CATEGORY_SOCKET, CHANGE_REMOVED): (
        "Confirm that the socket's absence is expected.",
    ),
}


def _socket_entity(identity: SocketIdentity) -> str:
    """The socket entity key, in lockstep with ``baseline/diff.py``."""
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, 3)


def _uid_key(uid: int | None) -> int:
    return -1 if uid is None else uid


def build_incident_report(
    *,
    session: Session,
    heuristics: HeuristicReport | None = None,
    permission_audits: Sequence[PackagePermissionAudit] = (),
    network_investigation: NetworkInvestigationSnapshot | None = None,
    process_snapshot: ProcessSnapshot | None = None,
    generated_at: datetime | None = None,
    sequence: int = 1,
    source: str = SOURCE_MANUAL,
    device_label: str | None = None,
    android_version: str | None = None,
) -> IncidentReport:
    """Build an :class:`IncidentReport` from the existing pipeline's output.

    All arguments are optional beyond *session*; missing inputs degrade the
    report honestly (fewer sections, "unavailable" values) instead of
    failing. Pure and deterministic: the same inputs yield the same report.
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    report_id = f"ATM-{generated_at:%Y%m%d}-{sequence:03d}"

    baseline = session.baseline
    current = session.current
    drift = session.drift_report

    # -- 1. Findings (structured, ordered by severity then type/entity) -----
    drift_refs = _drift_event_refs(drift)
    findings: list[Finding] = _build_drift_findings(drift, drift_refs)
    if heuristics is not None:
        findings.extend(_build_signal_findings(heuristics, drift_refs))
    findings.extend(_build_permission_findings(permission_audits))
    findings.sort(key=lambda f: (_severity_rank(f.severity), f.type, f.entity))
    findings = [
        Finding(
            finding_id=f"F-{index:03d}",
            type=f.type,
            severity=f.severity,
            title=f.title,
            description=f.description,
            entity=f.entity,
            timestamp=f.timestamp,
            category=f.category,
            change_type=f.change_type,
            reasons=f.reasons,
            evidence_refs=f.evidence_refs,
        )
        for index, f in enumerate(findings, start=1)
    ]

    # -- 2. Evidence rows (referenced by the findings) -----------------------
    proc_rows, proc_refs = _build_process_evidence(
        findings, baseline, current, process_snapshot
    )
    pkg_rows, pkg_refs = _build_package_evidence(
        findings, baseline, current, permission_audits, network_investigation
    )
    sock_rows, sock_refs = _build_socket_evidence(
        findings, baseline, current, network_investigation, pkg_refs
    )
    audit_rows = _build_permission_evidence(permission_audits)

    findings = [
        _attach_related_refs(f, current, proc_refs, pkg_refs, sock_refs) for f in findings
    ]

    # -- 3. Timeline / summary / severity / recommendations ------------------
    timeline = _build_timeline(session, heuristics, permission_audits)
    severity_summary = _build_severity_summary(findings)
    summary = _build_summary(drift, heuristics, findings, severity_summary)
    recommendations = _build_recommendations(findings)

    # -- 4. Device / metadata / integrity ------------------------------------
    device = DeviceInfo(
        serial=baseline.device_serial or None,
        label=device_label,
        android_version=android_version,
        collection_timestamp=current.created_at,
    )
    metadata = ReportMetadata(
        report_id=report_id,
        generated_at=generated_at,
        application_version=__version__,
        source=source,
        session_id=None,
        baseline_created_at=baseline.created_at,
    )

    report = IncidentReport(
        schema_version=SCHEMA_VERSION,
        metadata=metadata,
        device=device,
        summary=summary,
        severity_summary=severity_summary,
        timeline=timeline,
        findings=tuple(findings),
        process_evidence=proc_rows,
        network_evidence=sock_rows,
        package_evidence=pkg_rows,
        permission_evidence=audit_rows,
        recommendations=recommendations,
        integrity=None,
    )
    return _with_integrity(report, _build_integrity(report, generated_at))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _drift_event_refs(report: DriftReport) -> dict[DriftEvent, str]:
    """Assign deterministic ``D-001``… references to the drift events."""
    ordered = sorted(report.events, key=lambda e: (e.category, e.change_type, e.entity))
    return {event: f"D-{index:03d}" for index, event in enumerate(ordered, start=1)}


def _build_drift_findings(
    drift: DriftReport,
    refs: dict[DriftEvent, str],
) -> list[Finding]:
    """Every drift event becomes an INFO finding that preserves the diff
    engine's own explanation wording — facts are reported, not re-worded."""
    findings: list[Finding] = []
    for event in sorted(drift.events, key=lambda e: (e.category, e.change_type, e.entity)):
        description = (
            event.explanation if event.explanation else f"{event.change_type} {event.category}"
        )
        findings.append(
            Finding(
                finding_id="",
                type=FINDING_DRIFT,
                severity=event.severity,
                title=f"{event.category} {event.change_type}",
                description=description,
                entity=event.entity,
                timestamp=drift.compared_at,
                category=event.category,
                change_type=event.change_type,
                reasons=(description,),
                evidence_refs=(refs[event],),
            )
        )
    return findings


def _build_signal_findings(
    heuristics: HeuristicReport,
    drift_refs: dict[DriftEvent, str],
) -> list[Finding]:
    """One finding per existing SuspiciousSignal, preserving its reason,
    severity and entity verbatim; contributing drift events become refs."""
    refs_by_entity: dict[str, list[str]] = {}
    for event, ref in drift_refs.items():
        refs_by_entity.setdefault(event.entity, []).append(ref)

    findings: list[Finding] = []
    for signal in heuristics.signals:
        contributing = tuple(
            sorted(
                ref
                for entity, refs in refs_by_entity.items()
                if entity in signal.contributing_events
                for ref in refs
            )
        )
        findings.append(
            Finding(
                finding_id="",
                type=FINDING_SUSPICIOUS_SIGNAL,
                severity=signal.severity,
                title=signal.rule_id,
                description=signal.reason,
                entity=signal.entity,
                timestamp=heuristics.evaluated_at,
                reasons=(signal.reason,),
                evidence_refs=contributing,
            )
        )
    return findings


def _build_permission_findings(
    audits: Sequence[PackagePermissionAudit],
) -> list[Finding]:
    """One INFO finding per combination flag, using the analyzer's own
    "worth reviewing" description — never reworded, never escalated."""
    findings: list[Finding] = []
    for audit in audits:
        for flag in audit.combination_flags:
            findings.append(
                Finding(
                    finding_id="",
                    type=FINDING_PERMISSION_COMBINATION,
                    severity=SEVERITY_INFO,
                    title=flag.flag_id,
                    description=flag.description,
                    entity=audit.package_name,
                    timestamp=audit.read_at,
                    reasons=(flag.description,),
                )
            )
    return findings


def _attach_related_refs(
    finding: Finding,
    current: BaselineSnapshot,
    proc_refs: dict[tuple[str, int | None, str], str],
    pkg_refs: dict[tuple[str, int | None], str],
    sock_refs: dict[SocketIdentity, str],
) -> Finding:
    """Resolve a finding's entity to its evidence rows' references."""
    procs, pkgs, socks = _related_identities(finding.entity, current)
    return Finding(
        finding_id=finding.finding_id,
        type=finding.type,
        severity=finding.severity,
        title=finding.title,
        description=finding.description,
        entity=finding.entity,
        timestamp=finding.timestamp,
        category=finding.category,
        change_type=finding.change_type,
        reasons=finding.reasons,
        evidence_refs=finding.evidence_refs,
        related_processes=tuple(sorted(ref for p in procs if (ref := proc_refs.get(_proc_key(p))) is not None)),
        related_packages=tuple(sorted(ref for p in pkgs if (ref := pkg_refs.get((p.package_name, p.uid))) is not None)),
        related_sockets=tuple(sorted(ref for s in socks if (ref := sock_refs.get(s)) is not None)),
    )


def _related_identities(
    entity: str,
    current: BaselineSnapshot,
) -> tuple[list[ProcessRef], list[PackageIdentity], list[SocketIdentity]]:
    """Map a finding entity to identities in the current snapshot.

    Entities are the existing signal vocabulary: a process name, a package
    name, a socket entity key (``tcp:0.0.0.0:4444``) or ``uid=N`` (the
    multi-socket rule's entity). Anything unrecognized matches nothing.
    """
    if entity.startswith("uid="):
        try:
            uid = int(entity[4:])
        except ValueError:
            return [], [], []
        return (
            [r for r in current.processes if r.uid == uid],
            [p for p in current.packages if p.uid == uid],
            [s for s in current.sockets if s.uid == uid],
        )
    procs = [r for r in current.processes if r.process_name == entity]
    pkgs = [p for p in current.packages if p.package_name == entity]
    socks = [s for s in current.sockets if _socket_entity(s) == entity]
    return procs, pkgs, socks


# ---------------------------------------------------------------------------
# Evidence rows
# ---------------------------------------------------------------------------


def _proc_key(identity: ProcessRef) -> tuple[str, int | None, str]:
    return (identity.process_name, identity.uid, identity.classification.value)


def _baseline_status(
    identity: Any,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> str:
    in_current = (
        identity in current.processes
        or identity in current.packages
        or identity in current.sockets
    )
    in_baseline = (
        identity in baseline.processes
        or identity in baseline.packages
        or identity in baseline.sockets
    )
    if in_current and in_baseline:
        return STATUS_BASELINE
    if in_current:
        return CHANGE_NEW
    if in_baseline:
        return CHANGE_REMOVED
    return STATUS_BASELINE


def _collect_process_identities(
    findings: Sequence[Finding],
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> dict[tuple[str, int | None, str], ProcessRef]:
    """All process identities the report needs: those related to findings
    and those named by process drift events (from the snapshot that has
    them — the current one for NEW, the baseline one for REMOVED)."""
    identities: dict[tuple[str, int | None, str], ProcessRef] = {}
    for finding in findings:
        if finding.type != FINDING_DRIFT or finding.category == CATEGORY_PROCESS:
            for identity in _related_identities(finding.entity, current)[0]:
                identities.setdefault(_proc_key(identity), identity)
        if finding.type == FINDING_DRIFT and finding.category == CATEGORY_PROCESS:
            source = current if finding.change_type == CHANGE_NEW else baseline
            for identity in source.processes:
                if identity.process_name == finding.entity:
                    identities.setdefault(_proc_key(identity), identity)
    return identities


def _build_process_evidence(
    findings: Sequence[Finding],
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    process_snapshot: ProcessSnapshot | None,
) -> tuple[tuple[ProcessEvidence, ...], dict[tuple[str, int | None, str], str]]:
    """Process evidence rows, enriched with dynamic metrics from the latest
    process sample when an exact (name, uid) match exists — otherwise the
    metrics stay ``None`` ("unavailable"), never zero."""
    identities = _collect_process_identities(findings, baseline, current)
    by_metric: dict[tuple[str, int | None], Any] = {}
    if process_snapshot is not None:
        for info in process_snapshot.processes:
            by_metric[(info.name, info.uid)] = info

    keys = sorted(identities, key=lambda k: (k[0], _uid_key(k[1]), k[2]))
    rows: list[ProcessEvidence] = []
    refs: dict[tuple[str, int | None, str], str] = {}
    for index, key in enumerate(keys, start=1):
        identity = identities[key]
        info = by_metric.get((identity.process_name, identity.uid))
        reference = f"P-{index:03d}"
        refs[key] = reference
        rows.append(
            ProcessEvidence(
                reference=reference,
                process_name=identity.process_name,
                uid=identity.uid,
                classification=identity.classification.value,
                baseline_status=_baseline_status(identity, baseline, current),
                pid=info.pid if info is not None else None,
                state=info.state if info is not None else None,
                cpu_percent=info.cpu_percent if info is not None else None,
                memory_percent=info.memory_percent if info is not None else None,
            )
        )
    return tuple(rows), refs


def _collect_package_identities(
    findings: Sequence[Finding],
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    network_investigation: NetworkInvestigationSnapshot | None = None,
) -> dict[tuple[str, int | None], PackageIdentity]:
    identities: dict[tuple[str, int | None], PackageIdentity] = {}
    for finding in findings:
        if finding.type != FINDING_DRIFT or finding.category == CATEGORY_PACKAGE:
            for identity in _related_identities(finding.entity, current)[1]:
                identities.setdefault((identity.package_name, identity.uid), identity)
        if finding.type == FINDING_DRIFT and finding.category == CATEGORY_PACKAGE:
            source = current if finding.change_type == CHANGE_NEW else baseline
            for identity in source.packages:
                if identity.package_name == finding.entity:
                    identities.setdefault((identity.package_name, identity.uid), identity)
    # Packages that own sockets related to findings: the network snapshot's
    # uid→package mapping is authoritative when present; otherwise fall back
    # to the snapshot data itself (and the baseline for REMOVED sockets).
    for socket_identity in _collect_socket_identities(findings, baseline, current).values():
        if socket_identity.uid is None:
            continue
        names: tuple[str, ...] = ()
        if network_investigation is not None:
            names = network_investigation.uid_packages.get(socket_identity.uid, ())
        if not names:
            names = tuple(
                p.package_name for p in current.packages if p.uid == socket_identity.uid
            )
        if not names:
            names = tuple(
                p.package_name for p in baseline.packages if p.uid == socket_identity.uid
            )
        for name in names:
            for snapshot in (current, baseline):
                for identity in snapshot.packages:
                    if identity.package_name == name and identity.uid == socket_identity.uid:
                        identities.setdefault((identity.package_name, identity.uid), identity)
                        break
    return identities


def _build_package_evidence(
    findings: Sequence[Finding],
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    audits: Sequence[PackagePermissionAudit],
    network_investigation: NetworkInvestigationSnapshot | None = None,
) -> tuple[tuple[PackageEvidence, ...], dict[tuple[str, int | None], str]]:
    identities = _collect_package_identities(
        findings, baseline, current, network_investigation
    )
    audit_refs_by_package: dict[str, list[str]] = {}
    for index, audit in enumerate(
        sorted(audits, key=lambda a: (a.package_name, a.read_at.isoformat())), start=1
    ):
        audit_refs_by_package.setdefault(audit.package_name, []).append(f"AUD-{index:03d}")

    keys = sorted(identities, key=lambda k: (k[0], _uid_key(k[1])))
    rows: list[PackageEvidence] = []
    refs: dict[tuple[str, int | None], str] = {}
    for index, key in enumerate(keys, start=1):
        identity = identities[key]
        reference = f"PKG-{index:03d}"
        refs[key] = reference
        rows.append(
            PackageEvidence(
                reference=reference,
                package_name=identity.package_name,
                uid=identity.uid,
                baseline_status=_baseline_status(identity, baseline, current),
                audit_refs=tuple(sorted(audit_refs_by_package.get(identity.package_name, ()))),
            )
        )
    return tuple(rows), refs


def _collect_socket_identities(
    findings: Sequence[Finding],
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> dict[SocketIdentity, SocketIdentity]:
    identities: dict[SocketIdentity, SocketIdentity] = {}
    for finding in findings:
        if finding.type != FINDING_DRIFT or finding.category == CATEGORY_SOCKET:
            for identity in _related_identities(finding.entity, current)[2]:
                identities.setdefault(identity, identity)
        if finding.type == FINDING_DRIFT and finding.category == CATEGORY_SOCKET:
            source = current if finding.change_type == CHANGE_NEW else baseline
            for identity in source.sockets:
                if _socket_entity(identity) == finding.entity:
                    identities.setdefault(identity, identity)
    return identities


def _build_socket_evidence(
    findings: Sequence[Finding],
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    network_investigation: NetworkInvestigationSnapshot | None,
    pkg_refs: dict[tuple[str, int | None], str],
) -> tuple[tuple[NetworkEvidence, ...], dict[SocketIdentity, str]]:
    identities = _collect_socket_identities(findings, baseline, current)

    detail: dict[SocketIdentity, SocketInfo] = {}
    if network_investigation is not None:
        for identity in identities:
            candidates = [
                s
                for s in network_investigation.sockets
                if s.protocol == identity.protocol
                and s.local_address == identity.local_address
                and s.local_port == identity.local_port
            ]
            if candidates:
                candidates.sort(
                    key=lambda s: (s.remote_address or "", s.remote_port or -1, s.state or "")
                )
                detail[identity] = candidates[0]

    refs_by_package: dict[str, list[str]] = {}
    for (package_name, _uid), ref in pkg_refs.items():
        refs_by_package.setdefault(package_name, []).append(ref)

    keys = sorted(identities, key=lambda s: (s.protocol, s.local_address, s.local_port, _uid_key(s.uid)))
    rows: list[NetworkEvidence] = []
    refs: dict[SocketIdentity, str] = {}
    for index, key in enumerate(keys, start=1):
        identity = identities[key]
        info = detail.get(identity)
        reference = f"S-{index:03d}"
        refs[identity] = reference
        package_refs = ()
        if network_investigation is not None and identity.uid is not None:
            package_refs = tuple(
                sorted(
                    ref
                    for name in network_investigation.uid_packages.get(identity.uid, ())
                    for ref in refs_by_package.get(name, ())
                )
            )
        rows.append(
            NetworkEvidence(
                reference=reference,
                protocol=identity.protocol,
                local_address=identity.local_address,
                local_port=identity.local_port,
                remote_address=info.remote_address if info is not None else None,
                remote_port=info.remote_port if info is not None else None,
                state=info.state if info is not None else None,
                uid=identity.uid,
                baseline_status=_baseline_status(identity, baseline, current),
                package_refs=package_refs,
            )
        )
    return tuple(rows), refs


def _build_permission_evidence(
    audits: Sequence[PackagePermissionAudit],
) -> tuple[PermissionEvidence, ...]:
    """One evidence row per existing audit — the analyzer's output is
    consumed unchanged (including its parse_complete honesty flag)."""
    rows: list[PermissionEvidence] = []
    for index, audit in enumerate(
        sorted(audits, key=lambda a: (a.package_name, a.read_at.isoformat())), start=1
    ):
        granted = tuple(
            sorted(entry.name for entry in audit.permissions if entry.granted is True)
        )
        runtime_granted = tuple(
            sorted(
                entry.name
                for entry in audit.permissions
                if entry.granted is True and entry.permission_type == PERMISSION_RUNTIME
            )
        )
        rows.append(
            PermissionEvidence(
                reference=f"AUD-{index:03d}",
                package_name=audit.package_name,
                read_at=audit.read_at,
                parse_complete=audit.parse_complete,
                permissions=tuple(
                    sorted(audit.permissions, key=lambda e: (e.permission_type, e.name))
                ),
                granted_permissions=granted,
                runtime_granted_permissions=runtime_granted,
                combination_flags=audit.combination_flags,
                reasons=tuple(flag.description for flag in audit.combination_flags),
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def _build_timeline(
    session: Session,
    heuristics: HeuristicReport | None,
    audits: Sequence[PackagePermissionAudit],
) -> tuple[TimelineEvent, ...]:
    """Chronological timeline built only from real timestamps carried by
    the inputs — no timestamp is invented. Drift events are dated by the
    drift check's ``compared_at`` (that is when they were reported)."""
    events: list[TimelineEvent] = [
        TimelineEvent(
            event_type=EVENT_BASELINE_CREATED,
            description="Baseline snapshot created",
            timestamp=session.baseline.created_at,
            entity=session.baseline.device_serial or None,
        )
    ]
    for event in sorted(
        session.drift_report.events,
        key=lambda e: (e.category, e.change_type, e.entity),
    ):
        description = (
            event.explanation if event.explanation else f"{event.change_type} {event.category}"
        )
        events.append(
            TimelineEvent(
                event_type=EVENT_DRIFT_EVENT,
                description=f"{description}: {event.entity}",
                timestamp=session.drift_report.compared_at,
                severity=event.severity,
                entity=event.entity,
            )
        )
    events.append(
        TimelineEvent(
            event_type=EVENT_DRIFT_CHECKED,
            description="Drift check completed",
            timestamp=session.drift_report.compared_at,
        )
    )
    if heuristics is not None:
        events.append(
            TimelineEvent(
                event_type=EVENT_HEURISTICS_EVALUATED,
                description=(
                    f"Heuristic rules evaluated ({len(heuristics.rules_applied)} rules, "
                    f"{len(heuristics.signals)} signals)"
                ),
                timestamp=heuristics.evaluated_at,
            )
        )
        for signal in heuristics.signals:
            events.append(
                TimelineEvent(
                    event_type=EVENT_SIGNAL_GENERATED,
                    description=signal.reason,
                    timestamp=heuristics.evaluated_at,
                    severity=signal.severity,
                    entity=signal.entity,
                )
            )
    for audit in sorted(audits, key=lambda a: (a.package_name, a.read_at.isoformat())):
        events.append(
            TimelineEvent(
                event_type=EVENT_PERMISSION_AUDITED,
                description="Permission audit recorded",
                timestamp=audit.read_at,
                entity=audit.package_name,
            )
        )
    events.sort(
        key=lambda e: (
            e.timestamp if e.timestamp is not None else datetime.max.replace(tzinfo=timezone.utc),
            _TIMELINE_RANK.get(e.event_type, 99),
            e.description,
        )
    )
    return tuple(events)


# ---------------------------------------------------------------------------
# Summary / severity / recommendations
# ---------------------------------------------------------------------------


def _build_severity_summary(findings: Sequence[Finding]) -> SeveritySummary:
    return SeveritySummary(
        high=sum(1 for f in findings if f.severity == "HIGH"),
        medium=sum(1 for f in findings if f.severity == "MEDIUM"),
        low=0,
        info=sum(1 for f in findings if f.severity == "INFO"),
    )


def _build_summary(
    drift: DriftReport,
    heuristics: HeuristicReport | None,
    findings: Sequence[Finding],
    severity: SeveritySummary,
) -> ExecutiveSummary:
    signal_count = len(heuristics.signals) if heuristics is not None else 0
    parts = [
        f"The monitoring session identified {len(drift.events)} change(s) relative to "
        "the established baseline."
    ]
    if heuristics is not None:
        parts.append(
            f"{signal_count} suspicious signal(s) were generated "
            f"({severity.high} HIGH, {severity.medium} MEDIUM)."
        )
    else:
        parts.append("Heuristics were not evaluated for this session.")
    parts.append(f"{len(findings)} finding(s) were recorded in total.")
    parts.append(f"Overall assessment: {severity.assessment}.")
    return ExecutiveSummary(
        text=" ".join(parts),
        drift_change_count=len(drift.events),
        signal_count=signal_count,
        finding_count=len(findings),
        heuristics_evaluated=heuristics is not None,
    )


def _build_recommendations(findings: Sequence[Finding]) -> tuple[Recommendation, ...]:
    """Group the fixed per-type recommendation texts by the findings they
    apply to; sorted by text for determinism."""
    by_text: dict[str, list[str]] = {}
    for finding in findings:
        texts = _RECOMMENDATIONS.get(
            (finding.type, finding.category, finding.change_type),
            _RECOMMENDATIONS.get((finding.type, None, None), ()),
        )
        for text in texts:
            by_text.setdefault(text, []).append(finding.finding_id)
    return tuple(
        Recommendation(finding_refs=tuple(sorted(refs)), text=text)
        for text, refs in sorted(by_text.items())
    )


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def _canonical_payload(report: IncidentReport) -> str:
    """Canonical JSON of the report minus the integrity section (which
    cannot hash itself)."""
    from .renderers import report_to_dict

    payload = report_to_dict(report)
    payload.pop("integrity", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _build_integrity(report: IncidentReport, generated_at: datetime) -> IntegrityMetadata:
    digest = hashlib.sha256(_canonical_payload(report).encode("utf-8")).hexdigest()
    return IntegrityMetadata(
        generated_at=generated_at,
        application_version=report.metadata.application_version,
        schema_version=report.schema_version,
        session_id=report.metadata.session_id,
        evidence_sha256=digest,
    )


def _with_integrity(report: IncidentReport, integrity: IntegrityMetadata) -> IncidentReport:
    return IncidentReport(
        schema_version=report.schema_version,
        metadata=report.metadata,
        device=report.device,
        summary=report.summary,
        severity_summary=report.severity_summary,
        timeline=report.timeline,
        findings=report.findings,
        process_evidence=report.process_evidence,
        network_evidence=report.network_evidence,
        package_evidence=report.package_evidence,
        permission_evidence=report.permission_evidence,
        recommendations=report.recommendations,
        integrity=integrity,
    )