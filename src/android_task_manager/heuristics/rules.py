"""Heuristic rules — small, auditable, explainable risk signals.

Each rule is an independent function that consumes the facts-only diff
output (a :class:`DriftReport`) plus the two snapshots it was built from,
and returns zero or more :class:`SuspiciousSignal` objects. Rules never
modify the report, never call ADB, and never assign a severity outside the
fixed ``MEDIUM``/``HIGH`` vocabulary.

Cross-referencing events back to identities:

    ``DriftEvent.entity`` is the *stable identity key* the diff engine
    assigned when it emitted the event: a process name, a package name, or
    ``"<protocol>:<local_address>:<local_port>"`` for sockets (see
    ``baseline/diff.py``). Because *NEW* means "present in the current
    snapshot", a rule resolves an event back to the raw identity by looking
    that key up in the **current** snapshot — no UID information needs to be
    added to ``DriftEvent``, and ``baseline/diff.py`` stays facts-only.

    The socket-entity formatting is reproduced locally (``_socket_entity``)
    rather than importing the private helper from ``baseline/diff.py``;
    the two are kept in lockstep by test.

Rules and uncertainty:

    * A required category listed in ``report.unverified_categories`` skips
      the rule entirely — reasoning over a partially-read category would
      fabricate confidence.
    * ``None`` UIDs never match anything: "unknown" is never grouped with
      "known", so no rule fabricates an attribution.
    * Identity lookups are name/entity-keyed, exactly like the diff
      engine's entity strings (two distinct identities sharing one name
      resolve to the same event key — the rules then consider every
      matching identity, never picking one arbitrarily).
"""

from __future__ import annotations

from collections.abc import Callable

from ..baseline.models import (
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
from ..process.models import ProcessCategory
from .models import SEVERITY_HIGH, SEVERITY_MEDIUM, SuspiciousSignal

#: Stable rule identifiers (audit / traceability keys).
RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET = "NEW_PROCESS_WITH_ACTIVE_SOCKET"
RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS = "NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS"
RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS = "MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS"

RuleFunction = Callable[
    [DriftReport, BaselineSnapshot, BaselineSnapshot],
    list[SuspiciousSignal],
]

# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _socket_entity(identity: SocketIdentity) -> str:
    """The socket entity key, in lockstep with ``baseline/diff.py``."""
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _new_events(report: DriftReport, category: str) -> tuple[DriftEvent, ...]:
    return tuple(
        event for event in report.events
        if event.category == category and event.change_type == CHANGE_NEW
    )


def _category_unverified(report: DriftReport, category: str) -> bool:
    return category in report.unverified_categories


def _processes_by_name(snapshot: BaselineSnapshot) -> dict[str, tuple[ProcessRef, ...]]:
    """Map every current snapshot process name to all identities with it.

    Two identities may share a name (different UIDs); the diff events carry
    only the name key, so rules must consider every matching identity.
    """
    by_name: dict[str, list[ProcessRef]] = {}
    for identity in snapshot.processes:
        by_name.setdefault(identity.process_name, []).append(identity)
    return {name: tuple(refs) for name, refs in by_name.items()}


def _packages_by_name(snapshot: BaselineSnapshot) -> dict[str, PackageIdentity]:
    return {identity.package_name: identity for identity in snapshot.packages}


def _sockets_by_entity(snapshot: BaselineSnapshot) -> dict[str, tuple[SocketIdentity, ...]]:
    by_entity: dict[str, list[SocketIdentity]] = {}
    for identity in snapshot.sockets:
        by_entity.setdefault(_socket_entity(identity), []).append(identity)
    return {entity: tuple(sockets) for entity, sockets in by_entity.items()}


# ---------------------------------------------------------------------------
# Rule 1: new process + new socket owned by the same UID.
# ---------------------------------------------------------------------------


def rule_new_process_with_active_socket(
    report: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> list[SuspiciousSignal]:
    """MEDIUM — a new process is already communicating over the network.

    Fires once per new process that has at least one new socket whose
    attributed UID matches it. Does not fire when either category is
    unverified or when either UID is unknown.
    """
    if _category_unverified(report, CATEGORY_PROCESS) or _category_unverified(report, CATEGORY_SOCKET):
        return []

    processes_by_name = _processes_by_name(current)
    sockets_by_entity = _sockets_by_entity(current)
    new_socket_events = _new_events(report, CATEGORY_SOCKET)
    signals: list[SuspiciousSignal] = []
    for process_event in _new_events(report, CATEGORY_PROCESS):
        for process in processes_by_name.get(process_event.entity, ()):
            if process.uid is None:
                continue
            matching_sockets = [
                socket_event
                for socket_event in new_socket_events
                if any(
                    socket.uid is not None and socket.uid == process.uid
                    for socket in sockets_by_entity.get(socket_event.entity, ())
                )
            ]
            if not matching_sockets:
                continue
            count = len(matching_sockets)
            socket_word = "socket" if count == 1 else "sockets"
            signals.append(
                SuspiciousSignal(
                    rule_id=RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET,
                    severity=SEVERITY_MEDIUM,
                    entity=process.process_name,
                    reason=(
                        f"New process '{process.process_name}' appeared alongside "
                        f"{count} new network {socket_word} owned by the same UID "
                        f"({process.uid}) — a previously unseen process is already "
                        "communicating over the network."
                    ),
                    contributing_events=(process_event.entity,)
                    + tuple(socket.entity for socket in matching_sockets),
                )
            )
    return signals


# ---------------------------------------------------------------------------
# Rule 2: newly installed package with a new user-classified process.
# ---------------------------------------------------------------------------


def rule_new_unclassified_package_with_new_process(
    report: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> list[SuspiciousSignal]:
    """MEDIUM — a fresh install is already running as a user process.

    Fires once per new package that has at least one new, user-classified
    ("app") process sharing its UID. A package without a known UID never
    matches (no fabricated matching), and unverified categories skip the
    rule entirely.
    """
    if _category_unverified(report, CATEGORY_PACKAGE) or _category_unverified(report, CATEGORY_PROCESS):
        return []

    packages_by_name = _packages_by_name(current)
    processes_by_name = _processes_by_name(current)
    new_process_events = _new_events(report, CATEGORY_PROCESS)
    signals: list[SuspiciousSignal] = []
    for package_event in _new_events(report, CATEGORY_PACKAGE):
        package = packages_by_name.get(package_event.entity)
        if package is None or package.uid is None:
            continue
        matching_processes = [
            process_event
            for process_event in new_process_events
            if any(
                process.classification is ProcessCategory.USER
                and process.uid is not None
                and process.uid == package.uid
                for process in processes_by_name.get(process_event.entity, ())
            )
        ]
        if not matching_processes:
            continue
        process_names = [
            process.process_name
            for process_event in matching_processes
            for process in processes_by_name.get(process_event.entity, ())
        ]
        names = ", ".join(f"'{name}'" for name in process_names)
        signals.append(
            SuspiciousSignal(
                rule_id=RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS,
                severity=SEVERITY_MEDIUM,
                entity=package.package_name,
                reason=(
                    f"A newly installed package '{package.package_name}' immediately "
                    f"has a running user process ({names}) — worth confirming this "
                    "installation was expected."
                ),
                contributing_events=(package_event.entity,)
                + tuple(process.entity for process in matching_processes),
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Rule 3: several new listening sockets opened by one UID.
# ---------------------------------------------------------------------------


def rule_multiple_new_listening_sockets_same_process(
    report: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
) -> list[SuspiciousSignal]:
    """HIGH — one owner opened several new listening sockets in one check.

    Fires once per attributed UID with at least two new sockets. Unknown
    UIDs are never grouped, so no signal can be built on "unknown".
    """
    if _category_unverified(report, CATEGORY_SOCKET):
        return []

    sockets_by_entity = _sockets_by_entity(current)
    sockets_per_uid: dict[int, list[DriftEvent]] = {}
    for socket_event in _new_events(report, CATEGORY_SOCKET):
        for socket in sockets_by_entity.get(socket_event.entity, ()):
            if socket.uid is not None:
                sockets_per_uid.setdefault(socket.uid, []).append(socket_event)

    signals: list[SuspiciousSignal] = []
    for uid, socket_events in sorted(sockets_per_uid.items()):
        if len(socket_events) < 2:
            continue
        signals.append(
            SuspiciousSignal(
                rule_id=RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS,
                severity=SEVERITY_HIGH,
                entity=f"uid={uid}",
                reason=(
                    f"Uid {uid} opened {len(socket_events)} new listening sockets "
                    "in a single check — unusual for most apps and worth investigating."
                ),
                contributing_events=tuple(
                    sorted(socket.entity for socket in socket_events)
                ),
            )
        )
    return signals


#: (rule, stable id) registry for the evaluation entry point.
RULE_IDS: dict[RuleFunction, str] = {
    rule_new_process_with_active_socket: RULE_NEW_PROCESS_WITH_ACTIVE_SOCKET,
    rule_new_unclassified_package_with_new_process: RULE_NEW_UNCLASSIFIED_PACKAGE_WITH_NEW_PROCESS,
    rule_multiple_new_listening_sockets_same_process: RULE_MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS,
}