"""Investigation timeline — unified, deterministic event log + correlation.

The timeline folds every *existing* structured event into one
chronological log: baseline creation, drift facts (with their stability
classification), the stability analysis itself, heuristic evaluation,
signals and permission audits. It references evidence by the existing
identity vocabulary (``evidence_refs``) instead of embedding snapshots,
and it never fabricates timestamps — events whose source carried no time
sort last and stay ``None``.

Correlation resolves an entity key to its related processes, packages,
sockets and signals using the existing identity rules. Relationship
vocabulary is deliberately non-causal: ``RELATED_TO`` / ``OWNED_BY`` /
``ASSOCIATED_WITH`` / ``OBSERVED_ON`` — never "caused by".
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from ..baseline.export import Session
from ..baseline.models import (
    BaselineSnapshot,
    DriftEvent,
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from ..heuristics.models import HeuristicReport, SuspiciousSignal
from ..network_investigation.models import NetworkInvestigationSnapshot
from ..permissions.models import PackagePermissionAudit
from .models import (
    EVENT_BASELINE_CREATED,
    EVENT_DRIFT_CHECKED,
    EVENT_DRIFT_EVENT,
    EVENT_HEURISTICS_EVALUATED,
    EVENT_NOT_OBSERVED,
    EVENT_PERMISSION_AUDITED,
    EVENT_SIGNAL_GENERATED,
    EVENT_STABILITY_ANALYZED,
    EVENT_TRANSIENT_CHANGE,
    RELATION_OWNED_BY,
    RELATION_RELATED_TO,
    InvestigationEvent,
    RelatedEntities,
    StabilityReport,
)

#: Fixed event-type order for deterministic ties on equal timestamps.
_TIMELINE_RANK = {
    EVENT_BASELINE_CREATED: 0,
    EVENT_DRIFT_EVENT: 1,
    EVENT_TRANSIENT_CHANGE: 2,
    EVENT_NOT_OBSERVED: 3,
    EVENT_DRIFT_CHECKED: 4,
    EVENT_STABILITY_ANALYZED: 5,
    EVENT_HEURISTICS_EVALUATED: 6,
    EVENT_SIGNAL_GENERATED: 7,
    EVENT_PERMISSION_AUDITED: 8,
}


def _socket_entity(identity: SocketIdentity) -> str:
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _drift_events_sorted(drift) -> tuple[DriftEvent, ...]:
    return tuple(
        sorted(drift.events, key=lambda e: (e.category, e.change_type, e.entity))
    )


def build_investigation_timeline(
    *,
    session: Session,
    heuristics: HeuristicReport | None = None,
    stability: dict[str, StabilityReport] | None = None,
    audits: Sequence[PackagePermissionAudit] = (),
) -> tuple[InvestigationEvent, ...]:
    """Build the unified, deterministically ordered investigation timeline.

    All timestamps come from the inputs; events whose sources carry no
    time sort last with ``timestamp=None``. Event ids (``T-001``…) are
    assigned after ordering, so the ids are stable for equal inputs.
    """
    events: list[InvestigationEvent] = [
        InvestigationEvent(
            event_id="",
            event_type=EVENT_BASELINE_CREATED,
            title="Baseline snapshot created",
            description="Baseline snapshot created",
            timestamp=session.baseline.created_at,
            entity=session.baseline.device_serial or None,
            related_entities=(),
        )
    ]

    compared_at = session.drift_report.compared_at
    for event in _drift_events_sorted(session.drift_report):
        explanation = event.explanation or f"{event.change_type} {event.category}"
        bucket = _bucket_of(stability, event)
        if bucket == "transient":
            events.append(
                InvestigationEvent(
                    event_id="",
                    event_type=EVENT_TRANSIENT_CHANGE,
                    title="Transient change observed",
                    description=(
                        f"{explanation}: {event.entity} — observed but not "
                        "confirmed persistent"
                    ),
                    timestamp=compared_at,
                    severity=event.severity,
                    entity=event.entity,
                    evidence_refs=(event.entity,),
                )
            )
        elif bucket == "uncertain":
            events.append(
                InvestigationEvent(
                    event_id="",
                    event_type=EVENT_NOT_OBSERVED,
                    title="Change unconfirmed (incomplete read)",
                    description=(
                        f"{explanation}: {event.entity} — could not be confirmed "
                        "because the latest snapshot read was incomplete"
                    ),
                    timestamp=compared_at,
                    severity=event.severity,
                    entity=event.entity,
                    evidence_refs=(event.entity,),
                )
            )
        else:
            events.append(
                InvestigationEvent(
                    event_id="",
                    event_type=EVENT_DRIFT_EVENT,
                    title=f"{event.category} {event.change_type}",
                    description=f"{explanation}: {event.entity}",
                    timestamp=compared_at,
                    severity=event.severity,
                    entity=event.entity,
                    evidence_refs=(event.entity,),
                )
            )

    events.append(
        InvestigationEvent(
            event_id="",
            event_type=EVENT_DRIFT_CHECKED,
            title="Drift check completed",
            description="Drift check completed",
            timestamp=compared_at,
        )
    )

    if stability:
        for category in sorted(stability):
            report = stability[category]
            events.append(
                InvestigationEvent(
                    event_id="",
                    event_type=EVENT_STABILITY_ANALYZED,
                    title="Drift stability analyzed",
                    description=(
                        f"{category}: {len(report.meaningful_events)} meaningful, "
                        f"{len(report.transient_events)} transient, "
                        f"{len(report.uncertain_events)} unconfirmed change(s)"
                    ),
                    timestamp=compared_at,
                    severity=None,
                )
            )

    if heuristics is not None:
        events.append(
            InvestigationEvent(
                event_id="",
                event_type=EVENT_HEURISTICS_EVALUATED,
                title="Heuristics evaluated",
                description=(
                    f"Heuristic rules evaluated ({len(heuristics.rules_applied)} "
                    f"rules, {len(heuristics.signals)} signals)"
                ),
                timestamp=heuristics.evaluated_at,
            )
        )
        for signal in heuristics.signals:
            events.append(
                InvestigationEvent(
                    event_id="",
                    event_type=EVENT_SIGNAL_GENERATED,
                    title=signal.rule_id,
                    description=signal.reason,
                    timestamp=heuristics.evaluated_at,
                    severity=signal.severity,
                    entity=signal.entity,
                    evidence_refs=tuple(signal.contributing_events),
                )
            )

    for audit in sorted(audits, key=lambda a: (a.package_name, a.read_at.isoformat())):
        events.append(
            InvestigationEvent(
                event_id="",
                event_type=EVENT_PERMISSION_AUDITED,
                title="Permission audit recorded",
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
    return tuple(
        InvestigationEvent(
            event_id=f"T-{index:03d}",
            event_type=event.event_type,
            title=event.title,
            description=event.description,
            timestamp=event.timestamp,
            severity=event.severity,
            entity=event.entity,
            evidence_refs=event.evidence_refs,
            related_entities=event.related_entities,
        )
        for index, event in enumerate(events, start=1)
    )


def _bucket_of(
    stability: dict[str, StabilityReport] | None, event: DriftEvent
) -> str:
    """Which stability bucket *event* landed in ('' when not analyzed)."""
    if not stability:
        return ""
    report = stability.get(event.category)
    if report is None:
        return "meaningful"
    if event in report.meaningful_events:
        return "meaningful"
    if event in report.transient_events:
        return "transient"
    if event in report.uncertain_events:
        return "uncertain"
    return "meaningful"


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


def correlate_entity(
    entity: str,
    *,
    current: BaselineSnapshot,
    network_investigation: NetworkInvestigationSnapshot | None = None,
    heuristics: HeuristicReport | None = None,
) -> RelatedEntities:
    """Resolve *entity* (existing identity vocabulary) to related entities.

    Handles process names, package names, socket entity keys and
    ``uid=N`` (the multi-socket rule's entity). Sockets owned by a UID
    that matches a related process use ``OWNED_BY``; everything else
    uses ``RELATED_TO`` — relationship words only, never causation.
    """
    processes: tuple[ProcessRef, ...] = ()
    packages: tuple[PackageIdentity, ...] = ()
    sockets: tuple[SocketIdentity, ...] = ()

    if entity.startswith("uid="):
        try:
            uid = int(entity[4:])
        except ValueError:
            return RelatedEntities(entity=entity)
        processes = tuple(sorted(
            (r for r in current.processes if r.uid == uid),
            key=lambda r: (r.process_name, -1 if r.uid is None else r.uid),
        ))
        packages = tuple(sorted(
            (p for p in current.packages if p.uid == uid),
            key=lambda p: (p.package_name, -1 if p.uid is None else p.uid),
        ))
        sockets = tuple(sorted(
            (s for s in current.sockets if s.uid == uid),
            key=lambda s: (s.protocol, s.local_address, s.local_port),
        ))
    else:
        sockets = tuple(sorted(
            (s for s in current.sockets if _socket_entity(s) == entity),
            key=lambda s: (s.protocol, s.local_address, s.local_port),
        ))
        owner_uid = sockets[0].uid if sockets else None
        processes = tuple(sorted(
            (r for r in current.processes if r.process_name == entity or (
                owner_uid is not None and r.uid == owner_uid
            )),
            key=lambda r: (r.process_name, -1 if r.uid is None else r.uid),
        ))
        packages = tuple(sorted(
            (p for p in current.packages if p.package_name == entity or (
                owner_uid is not None and p.uid == owner_uid
            )),
            key=lambda p: (p.package_name, -1 if p.uid is None else p.uid),
        ))

    signals: list[SuspiciousSignal] = []
    if heuristics is not None:
        for signal in heuristics.signals:
            if signal.entity == entity or entity in signal.contributing_events:
                signals.append(signal)
    signals.sort(key=lambda s: (s.severity, s.rule_id, s.entity))

    relation = RELATION_RELATED_TO
    if sockets:
        uid = sockets[0].uid
        if uid is not None and any(p.uid == uid for p in processes):
            relation = RELATION_OWNED_BY

    return RelatedEntities(
        entity=entity,
        relation=relation,
        processes=processes,
        packages=packages,
        sockets=sockets,
        signals=tuple(signals),
    )


__all__ = [
    "build_investigation_timeline",
    "correlate_entity",
]