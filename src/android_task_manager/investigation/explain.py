"""Evidence explanations — "why was this flagged?".

Every existing :class:`SuspiciousSignal` can be explained with a
deterministic set of *facts* derived from already-collected data — the
baseline snapshot, the current snapshot, the latest process sample, the
socket tables, the package map, permission audits and the signal itself.
No LLM, no GUI-text scraping, no new detection.

Fact vs. judgment (non-negotiable): the output contains facts only —
"Socket was not present in baseline.", "CPU was 93%.", "Signal severity
is HIGH." It never produces "This is malware." / "Your phone is hacked."
A fact is only emitted when the underlying value exists; everything else
is simply omitted, never guessed.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..baseline.models import (
    CHANGE_NEW,
    BaselineSnapshot,
    DriftReport,
    SocketIdentity,
)
from ..heuristics.models import SuspiciousSignal
from ..network_investigation.models import NetworkInvestigationSnapshot
from ..permissions.models import PackagePermissionAudit
from ..process.models import ProcessSnapshot
from .models import (
    FACT_BASELINE,
    FACT_NETWORK,
    FACT_PACKAGE,
    FACT_PERMISSION,
    FACT_PROCESS,
    FACT_SIGNAL,
    AttributionState,
    EntityStability,
    EvidenceExplanation,
    EvidenceFact,
    ObservationState,
    SocketAttribution,
)

_AID_APP = 10000

_FACT_CATEGORY_RANK = {
    FACT_BASELINE: 0,
    FACT_PROCESS: 1,
    FACT_NETWORK: 2,
    FACT_PACKAGE: 3,
    FACT_PERMISSION: 4,
    FACT_SIGNAL: 5,
}


def _socket_entity(identity: SocketIdentity) -> str:
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _matches(entity: str, identity) -> bool:
    if entity.startswith("uid="):
        try:
            uid = int(entity[4:])
        except ValueError:
            return False
        return getattr(identity, "uid", None) == uid
    if getattr(identity, "process_name", None) == entity:
        return True
    if getattr(identity, "package_name", None) == entity:
        return True
    return isinstance(identity, SocketIdentity) and _socket_entity(identity) == entity


def _is_new(entity: str, drift: DriftReport) -> bool:
    return any(
        event.change_type == CHANGE_NEW and event.entity == entity
        for event in drift.events
    )


def _socket_state(
    entity: str,
    network_investigation: NetworkInvestigationSnapshot | None,
) -> str | None:
    if network_investigation is None:
        return None
    for socket in network_investigation.sockets:
        if _socket_entity(socket) == entity:
            return socket.state
    return None


def _socket_identities_for(reference: str, current: BaselineSnapshot) -> tuple[SocketIdentity, ...]:
    """Resolve a contributing-event reference to its socket identities.

    References are the existing entity vocabulary; only socket-shaped
    references (``protocol:address:port``) resolve to sockets.
    """
    parts = reference.split(":")
    if len(parts) != 3:
        return ()
    protocol, address, port = parts
    try:
        port_value = int(port)
    except ValueError:
        return ()
    return tuple(
        sorted(
            (
                s
                for s in current.sockets
                if s.protocol == protocol
                and s.local_address == address
                and s.local_port == port_value
            ),
            key=lambda s: (
                s.protocol,
                s.local_address,
                s.local_port,
                -1 if s.uid is None else s.uid,
            ),
        )
    )


def _explain_signal_facts(
    signal: SuspiciousSignal,
    *,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    drift: DriftReport,
    processes: ProcessSnapshot | None,
    network_investigation: NetworkInvestigationSnapshot | None,
    audits: Sequence[PackagePermissionAudit],
    attribution: SocketAttribution | None,
    entity_stability: EntityStability | None,
) -> tuple[EvidenceFact, ...]:
    facts: list[EvidenceFact] = []
    entity = signal.entity

    # -- Baseline + stability facts ---------------------------------------
    if entity.startswith("uid="):
        try:
            uid = int(entity[4:])
        except ValueError:
            uid = None
        processes_here = [r for r in current.processes if r.uid == uid] if uid is not None else []
        packages_here = [p for p in current.packages if p.uid == uid] if uid is not None else []
        sockets_here = [s for s in current.sockets if s.uid == uid] if uid is not None else []
    else:
        processes_here = [r for r in current.processes if r.process_name == entity]
        packages_here = [p for p in current.packages if p.package_name == entity]
        sockets_here = [s for s in current.sockets if _socket_entity(s) == entity]

    if entity.startswith("uid=") or sockets_here:
        if _is_new(entity, drift):
            facts.append(
                EvidenceFact(FACT_BASELINE, "Socket was not present in baseline.", entity)
            )
        else:
            facts.append(EvidenceFact(FACT_BASELINE, "Socket was present in baseline.", entity))
    elif processes_here:
        if _is_new(entity, drift):
            facts.append(
                EvidenceFact(FACT_BASELINE, "Owning process was newly observed.", entity)
            )
        else:
            facts.append(EvidenceFact(FACT_BASELINE, "Process was present in baseline.", entity))
    elif packages_here:
        if _is_new(entity, drift):
            facts.append(EvidenceFact(FACT_BASELINE, "Package was newly observed.", entity))
        else:
            facts.append(EvidenceFact(FACT_BASELINE, "Package was present in baseline.", entity))

    if entity_stability is not None:
        if entity_stability.state is ObservationState.PERSISTENT:
            facts.append(
                EvidenceFact(
                    FACT_BASELINE,
                    "The change persisted across multiple observations.",
                    entity,
                )
            )
        elif entity_stability.state is ObservationState.TRANSIENT:
            facts.append(
                EvidenceFact(
                    FACT_BASELINE,
                    "The change was observed but not confirmed persistent.",
                    entity,
                )
            )
        elif entity_stability.state is ObservationState.UNCERTAIN:
            facts.append(
                EvidenceFact(
                    FACT_BASELINE,
                    "The change could not be confirmed (incomplete snapshot read).",
                    entity,
                )
            )

    # -- Process facts ------------------------------------------------------
    if processes is not None:
        matched: list = []
        if entity.startswith("uid="):
            try:
                uid = int(entity[4:])
            except ValueError:
                uid = None
            matched = [p for p in processes.processes if p.uid == uid] if uid is not None else []
        else:
            matched = [
                p for p in processes.processes
                if p.name == entity
                or any(r.process_name == entity and p.uid == r.uid for r in processes_here)
            ]
        matched.sort(key=lambda p: p.pid)
        for info in matched[:3]:
            facts.append(
                EvidenceFact(FACT_PROCESS, f"PID: {info.pid}.", entity)
            )
            facts.append(EvidenceFact(FACT_PROCESS, f"Process name: {info.name}.", entity))
            if info.uid is not None:
                facts.append(EvidenceFact(FACT_PROCESS, f"UID: {info.uid}.", entity))
            if info.cpu_percent is not None:
                facts.append(
                    EvidenceFact(FACT_PROCESS, f"CPU was {info.cpu_percent:.0f}%.", entity)
                )
            if info.memory_percent is not None:
                facts.append(
                    EvidenceFact(
                        FACT_PROCESS, f"Memory was {info.memory_percent:.0f}%.", entity
                    )
                )
            if info.ppid is not None:
                facts.append(EvidenceFact(FACT_PROCESS, f"Parent PID: {info.ppid}.", entity))

    # -- Network facts --------------------------------------------------------
    for socket in sockets_here[:3]:
        facts.append(
            EvidenceFact(FACT_NETWORK, f"Protocol: {socket.protocol}.", _socket_entity(socket))
        )
        facts.append(
            EvidenceFact(
                FACT_NETWORK,
                f"Local address: {socket.local_address}:{socket.local_port}.",
                _socket_entity(socket),
            )
        )
        state = _socket_state(_socket_entity(socket), network_investigation)
        if state:
            facts.append(
                EvidenceFact(FACT_NETWORK, f"Socket state: {state}.", _socket_entity(socket))
            )
            if state == "LISTEN":
                facts.append(
                    EvidenceFact(FACT_NETWORK, "Socket is listening.", _socket_entity(socket))
                )

    # Socket facts referenced by the signal's contributing events (e.g. the
    # process+active-socket rule names its socket entity in contributing
    # events) — the signal's evidence, not a guess.
    contributed_sockets = tuple(
        socket
        for reference in signal.contributing_events
        for socket in _socket_identities_for(reference, current)
        if _socket_entity(socket) not in {_socket_entity(s) for s in sockets_here}
    )
    for socket in contributed_sockets[:3]:
        facts.append(
            EvidenceFact(
                FACT_NETWORK,
                f"Contributing socket: {_socket_entity(socket)}.",
                _socket_entity(socket),
            )
        )
        state = _socket_state(_socket_entity(socket), network_investigation)
        if state:
            facts.append(
                EvidenceFact(
                    FACT_NETWORK, f"Socket state: {state}.", _socket_entity(socket)
                )
            )
            if state == "LISTEN":
                facts.append(
                    EvidenceFact(
                        FACT_NETWORK, "Socket is listening.", _socket_entity(socket)
                    )
                )

    # -- Package facts ---------------------------------------------------------
    for package in packages_here[:3]:
        facts.append(EvidenceFact(FACT_PACKAGE, f"Package: {package.package_name}.", package.package_name))
        if package.uid is not None:
            tier = "system" if package.uid < _AID_APP else "user"
            facts.append(
                EvidenceFact(
                    FACT_PACKAGE,
                    f"Package classification: {tier} (uid {package.uid}).",
                    package.package_name,
                )
            )

    # -- Permission facts (existing audit wording, preserved) ------------------
    for audit in audits:
        if any(p.package_name == audit.package_name for p in packages_here):
            for flag in audit.combination_flags:
                facts.append(
                    EvidenceFact(
                        FACT_PERMISSION,
                        f"{audit.package_name}: {flag.description}",
                        audit.package_name,
                    )
                )

    # -- Attribution fact --------------------------------------------------------
    if attribution is not None:
        label = {
            AttributionState.FULL: "full (socket → process → package)",
            AttributionState.PARTIAL: "partial (UID-level only)",
            AttributionState.UNAVAILABLE: "unavailable",
        }[attribution.attribution_state]
        facts.append(
            EvidenceFact(
                FACT_PROCESS,
                f"Socket ownership attribution: {label}.",
                _socket_entity(attribution.socket),
            )
        )

    # -- Signal fact ---------------------------------------------------------------
    facts.append(EvidenceFact(FACT_SIGNAL, f"Signal severity is {signal.severity}.", signal.rule_id))

    return tuple(
        sorted(facts, key=lambda f: (_FACT_CATEGORY_RANK.get(f.category, 9), f.text))
    )


def explain_signal(
    signal: SuspiciousSignal,
    *,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    drift: DriftReport,
    processes: ProcessSnapshot | None = None,
    network_investigation: NetworkInvestigationSnapshot | None = None,
    audits: Sequence[PackagePermissionAudit] = (),
    attribution: SocketAttribution | None = None,
    entity_stability: EntityStability | None = None,
) -> EvidenceExplanation:
    """Explain *signal* with facts derived from the supplied evidence.

    Every fact is traceable to the entity key in ``reference``. Missing
    inputs degrade the explanation (fewer facts) instead of failing or
    guessing.
    """
    return EvidenceExplanation(
        signal=signal,
        headline=signal.reason,
        facts=_explain_signal_facts(
            signal,
            baseline=baseline,
            current=current,
            drift=drift,
            processes=processes,
            network_investigation=network_investigation,
            audits=audits,
            attribution=attribution,
            entity_stability=entity_stability,
        ),
    )


def entity_stability_for(
    entity: str,
    stability: Sequence[EntityStability] | None,
) -> EntityStability | None:
    """Find the stability record for an entity key (any category)."""
    if not stability:
        return None
    return next((record for record in stability if record.identity_key == entity), None)


__all__ = [
    "entity_stability_for",
    "explain_signal",
]