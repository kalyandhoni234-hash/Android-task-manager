"""Stability analysis — noise-resistant drift classification.

The raw diff engine (``baseline/diff.py``) reports structural facts only:
what is NEW and what is REMOVED between two snapshots. On a real device
that is noisy — short-lived kernel workers and app churn appear and
disappear between samples. This module adds the *temporal* layer:

    RAW SNAPSHOT DIFFERENCE
            |
    OBSERVATION QUALITY   (COMPLETE / PARTIAL / FAILED)
            |
    TEMPORAL STABILITY    (STABLE / TRANSIENT / PERSISTENT / UNCERTAIN)
            |
    MEANINGFUL DRIFT

Rules (all count-based — the existing polling architecture supplies the
window, never an arbitrary wall-clock delay):

* **Presence is real even in a PARTIAL read**: an identity observed in a
  partial snapshot was genuinely there, so consecutive-presence counting
  does not require COMPLETE reads.
* **Absence requires COMPLETE reads**: an identity absent from a PARTIAL
  or FAILED observation is *NOT_OBSERVED*, never REMOVED. Confirmed
  removal needs the identity absent from repeated consecutive COMPLETE
  observations.
* **Kernel processes are not ignored**: churn makes them TRANSIENT like
  any other short-lived identity; a kernel process that stays is
  PERSISTENT and remains detectable.
* **Critical system processes get no special list**: absence in a partial
  snapshot is UNCERTAIN, absence in repeated complete snapshots is a
  meaningful REMOVED — the same honest rules as everything else.
* **Package drift is not stabilized**: package installation is a discrete
  verified read (``pm list packages``); transient churn is a process
  phenomenon, so package events pass through unchanged.

Nothing is destroyed: every raw event lands in exactly one bucket
(meaningful / transient / uncertain) and the report keeps them all.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

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
from ..network_investigation.models import NetworkInvestigationSnapshot
from ..process.models import ProcessSnapshot
from .completeness import baseline_category_completeness
from .models import (
    STABILITY_MEANINGFUL,
    STABILITY_TRANSIENT,
    STABILITY_UNCERTAIN,
    EntityStability,
    Observation,
    ObservationState,
    SnapshotCompleteness,
    StabilityReport,
)

#: Consecutive observations required before a new identity is promoted to
#: PERSISTENT (and before a baseline identity's absence is confirmed as
#: REMOVED). Count-based, so it tracks the existing polling cadence — the
#: same value on a 2 s or a 30 s poll means "observed again, then again".
MIN_PERSISTENT_OBSERVATIONS = 2

#: Maximum observations retained per category by the tracker (bounded
#: memory; the window is the "recent observations" evidence pool).
TRACKER_WINDOW = 50

#: Categories the stability analysis covers. Package events pass through
#: unchanged (see the module docstring).
STABILITY_CATEGORIES = (CATEGORY_PROCESS, CATEGORY_SOCKET)


# ---------------------------------------------------------------------------
# Per-identity state classification
# ---------------------------------------------------------------------------


def classify_entity_state(
    identity,
    *,
    identity_in_baseline: bool,
    series: Sequence[Observation],
    persistent_observations: int = MIN_PERSISTENT_OBSERVATIONS,
) -> ObservationState:
    """Classify one identity over an observation series (oldest first).

    ``identity_in_baseline`` is whether the identity was present in the
    baseline snapshot (a REMOVED candidate) or not (a NEW candidate).

    The series is the evidence pool; the newest observation is "now".
    With no observations at all the state is UNCERTAIN — no evidence,
    no claim.
    """
    if not series:
        return ObservationState.UNCERTAIN

    presence_streak = 0
    for obs in reversed(series):
        if identity in obs.identities:
            presence_streak += 1
        else:
            break

    absent_complete_streak = 0
    for obs in reversed(series):
        if obs.completeness is not SnapshotCompleteness.COMPLETE:
            break  # an incomplete read interrupts confirmed-absence evidence
        if identity in obs.identities:
            break
        absent_complete_streak += 1

    latest = series[-1]
    in_latest = identity in latest.identities

    if identity_in_baseline:
        if in_latest:
            return ObservationState.STABLE
        if latest.completeness is not SnapshotCompleteness.COMPLETE:
            return ObservationState.UNCERTAIN  # NOT_OBSERVED, not REMOVED
        if absent_complete_streak >= persistent_observations:
            return ObservationState.REMOVED
        return ObservationState.TRANSIENT  # absent once; not yet confirmed

    if presence_streak >= persistent_observations:
        return ObservationState.PERSISTENT
    if presence_streak >= 1:
        return ObservationState.TRANSIENT  # observed; not yet confirmed
    return ObservationState.UNCERTAIN  # never actually observed


# ---------------------------------------------------------------------------
# Drift stabilization (per category)
# ---------------------------------------------------------------------------


def _socket_entity(identity: SocketIdentity) -> str:
    return f"{identity.protocol}:{identity.local_address}:{identity.local_port}"


def _entity_key(category: str, identity) -> str:
    if category == CATEGORY_PROCESS:
        return identity.process_name
    if category == CATEGORY_SOCKET:
        return _socket_entity(identity)
    return identity.package_name


def _entity_matches(category: str, identity, entity: str) -> bool:
    return _entity_key(category, identity) == entity


def _candidate_identities(
    category: str,
    entity: str,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    series: Sequence[Observation],
) -> tuple:
    """Every identity matching *entity* across the evidence pool."""
    seen: dict = {}
    if category == CATEGORY_PROCESS:
        for identity in (*baseline.processes, *current.processes):
            if identity.process_name == entity:
                seen.setdefault((identity.uid, identity.process_name, identity.classification), identity)
        for obs in series:
            for identity in obs.identities:
                if (
                    isinstance(identity, ProcessRef)
                    and identity.process_name == entity
                ):
                    seen.setdefault((identity.uid, identity.process_name, identity.classification), identity)
        return tuple(seen.values())
    if category == CATEGORY_SOCKET:
        for identity in (*baseline.sockets, *current.sockets):
            if _socket_entity(identity) == entity:
                seen.setdefault((identity.protocol, identity.local_address, identity.local_port, identity.uid), identity)
        for obs in series:
            for identity in obs.identities:
                if isinstance(identity, SocketIdentity) and _socket_entity(identity) == entity:
                    seen.setdefault((identity.protocol, identity.local_address, identity.local_port, identity.uid), identity)
        return tuple(seen.values())
    return ()


def _in_baseline(category: str, identity, baseline: BaselineSnapshot) -> bool:
    if category == CATEGORY_PROCESS:
        return identity in baseline.processes
    return identity in baseline.sockets


def _bucket_for(
    category: str,
    event: DriftEvent,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    series: Sequence[Observation],
    *,
    persistent_observations: int,
) -> str:
    """Bucket one raw drift event: meaningful / transient / uncertain."""
    identities = _candidate_identities(category, event.entity, baseline, current, series)
    if not identities:
        # No identity data anywhere for this entity — the raw fact stands
        # as reported, but its stability cannot be confirmed.
        return STABILITY_UNCERTAIN

    states = [
        classify_entity_state(
            identity,
            identity_in_baseline=_in_baseline(category, identity, baseline),
            series=series,
            persistent_observations=persistent_observations,
        )
        for identity in identities
    ]
    if event.change_type == CHANGE_NEW:
        if any(s is ObservationState.PERSISTENT for s in states):
            return STABILITY_MEANINGFUL
        if any(s is ObservationState.UNCERTAIN for s in states):
            return STABILITY_UNCERTAIN
        return STABILITY_TRANSIENT
    # REMOVED event
    if any(s is ObservationState.REMOVED for s in states):
        return STABILITY_MEANINGFUL
    if any(s is ObservationState.UNCERTAIN for s in states):
        return STABILITY_UNCERTAIN
    return STABILITY_TRANSIENT


def _entity_stabilities(
    category: str,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    series: Sequence[Observation],
    *,
    persistent_observations: int,
) -> tuple[EntityStability, ...]:
    """Per-identity stability evidence for every identity in the pool."""
    keys: dict = {}
    if category == CATEGORY_PROCESS:
        pool = (*baseline.processes, *current.processes, *(
            i for obs in series for i in obs.identities if isinstance(i, ProcessRef)
        ))
        for identity in pool:
            keys.setdefault((identity.process_name, identity.uid, identity.classification), identity)
        order = sorted(
            keys.values(),
            key=lambda i: (i.process_name, -1 if i.uid is None else i.uid, i.classification.value),
        )
    elif category == CATEGORY_SOCKET:
        pool = (*baseline.sockets, *current.sockets, *(
            i for obs in series for i in obs.identities if isinstance(i, SocketIdentity)
        ))
        for identity in pool:
            keys.setdefault((identity.protocol, identity.local_address, identity.local_port, identity.uid), identity)
        order = sorted(
            keys.values(),
            key=lambda i: (i.protocol, i.local_address, i.local_port, -1 if i.uid is None else i.uid),
        )
    else:
        return ()

    records: list[EntityStability] = []
    for identity in order:
        in_baseline = _in_baseline(category, identity, baseline)
        state = classify_entity_state(
            identity,
            identity_in_baseline=in_baseline,
            series=series,
            persistent_observations=persistent_observations,
        )
        count = sum(1 for obs in series if identity in obs.identities)
        consecutive = 0
        for obs in reversed(series):
            if identity in obs.identities:
                consecutive += 1
            else:
                break
        times = [obs.timestamp for obs in series if identity in obs.identities and obs.timestamp is not None]
        records.append(
            EntityStability(
                identity_key=_entity_key(category, identity),
                state=state,
                observation_count=count,
                consecutive_observations=consecutive,
                first_observed=min(times) if times else None,
                last_observed=max(times) if times else None,
            )
        )
    return tuple(records)


def _summary(category: str, meaningful: int, transient: int, uncertain: int) -> str:
    parts: list[str] = []
    if transient:
        parts.append(f"{transient} {category} change(s) were observed and classified as non-persistent.")
    if uncertain:
        parts.append(
            f"{uncertain} {category} change(s) could not be confirmed because the "
            "latest snapshot read was incomplete."
        )
    return " ".join(parts) if parts else "All observed changes were confirmed stable."


def stabilize_drift(
    drift: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    series: dict[str, Sequence[Observation]] | None = None,
    *,
    persistent_observations: int = MIN_PERSISTENT_OBSERVATIONS,
) -> dict[str, StabilityReport]:
    """Classify every raw drift event into meaningful / transient / uncertain.

    ``series`` maps a category to its observation window (oldest first);
    the *current* snapshot is always appended as the final observation
    with its true completeness, so a drift check without any tracker
    history still classifies against the check itself.

    Returns one :class:`StabilityReport` per category; categories without
    a stability analysis (packages) pass every event through as
    meaningful.
    """
    series_by_category: dict[str, tuple[Observation, ...]] = {
        category: tuple(series.get(category, ()) if series else ())
        for category in STABILITY_CATEGORIES
    }
    reports: dict[str, StabilityReport] = {}
    events_by_category: dict[str, list[DriftEvent]] = {}
    for event in drift.events:
        events_by_category.setdefault(event.category, []).append(event)

    for category in sorted(events_by_category):
        raw = tuple(sorted(events_by_category[category], key=lambda e: (e.change_type, e.entity)))
        if category not in STABILITY_CATEGORIES:
            reports[category] = StabilityReport(
                category=category,
                events=raw,
                meaningful_events=raw,
                summary="Package changes are structural facts and were not stabilized.",
            )
            continue

        observation_series = series_by_category[category] + (
            Observation(
                completeness=baseline_category_completeness(current, category),
                identities=_current_identities(current, category),
            ),
        )
        meaningful: list[DriftEvent] = []
        transient: list[DriftEvent] = []
        uncertain: list[DriftEvent] = []
        for event in raw:
            bucket = _bucket_for(
                category,
                event,
                baseline,
                current,
                observation_series,
                persistent_observations=persistent_observations,
            )
            if bucket == STABILITY_MEANINGFUL:
                meaningful.append(event)
            elif bucket == STABILITY_TRANSIENT:
                transient.append(event)
            else:
                uncertain.append(event)

        reports[category] = StabilityReport(
            category=category,
            events=raw,
            meaningful_events=tuple(meaningful),
            transient_events=tuple(transient),
            uncertain_events=tuple(uncertain),
            entities=_entity_stabilities(
                category,
                baseline,
                current,
                observation_series,
                persistent_observations=persistent_observations,
            ),
            summary=_summary(category, len(meaningful), len(transient), len(uncertain)),
        )
    return reports


def _current_identities(current: BaselineSnapshot, category: str) -> frozenset:
    if category == CATEGORY_PROCESS:
        return frozenset(current.processes)
    return frozenset(current.sockets)


# ---------------------------------------------------------------------------
# Observation tracking (pure, GUI-independent)
# ---------------------------------------------------------------------------


class ObservationTracker:
    """Bounded per-category window of recent observations.

    Records raw collector snapshots as :class:`Observation` values. The
    window is capped (``TRACKER_WINDOW`` per category) so memory stays
    bounded on long sessions. Re-emitted cached snapshots (same
    timestamp) are skipped — they are not new observations.
    """

    def __init__(self, window: int = TRACKER_WINDOW) -> None:
        self._window = window
        self._series: dict[str, deque[Observation]] = {
            CATEGORY_PROCESS: deque(maxlen=window),
            CATEGORY_SOCKET: deque(maxlen=window),
        }
        self._last_timestamp: dict[str, float | None] = {
            CATEGORY_PROCESS: None,
            CATEGORY_SOCKET: None,
        }

    def reset(self) -> None:
        """Clear the window (a fresh baseline invalidates old evidence)."""
        for category in self._series:
            self._series[category].clear()
            self._last_timestamp[category] = None

    def record(
        self,
        category: str,
        completeness: SnapshotCompleteness,
        identities: Sequence[ProcessRef | PackageIdentity | SocketIdentity],
        timestamp: float | None = None,
    ) -> None:
        """Record one observation, skipping re-emitted cached snapshots."""
        if category not in self._series:
            return
        if timestamp is not None and timestamp == self._last_timestamp[category]:
            return
        self._last_timestamp[category] = timestamp
        self._series[category].append(
            Observation(
                completeness=completeness,
                identities=frozenset(identities),
                timestamp=timestamp,
            )
        )

    def record_process_snapshot(self, snapshot: ProcessSnapshot) -> None:
        """Record a monitor process sample (COMPLETE — it was just read).

        Placeholder rows (``<pid N>``, top-only) are excluded exactly like
        the baseline snapshot builder excludes them, so the identity
        vocabulary matches the diff engine's.
        """
        identities: list[ProcessRef] = []
        for info in snapshot.processes:
            name = info.name.strip()
            if name.startswith("<") and name.endswith(">"):
                continue
            identities.append(
                ProcessRef(uid=info.uid, process_name=name, classification=info.category)
            )
        self.record(
            CATEGORY_PROCESS,
            SnapshotCompleteness.COMPLETE,
            identities,
            timestamp=snapshot.timestamp,
        )

    def record_network_snapshot(
        self, snapshot: NetworkInvestigationSnapshot | None
    ) -> None:
        """Record a socket-table observation with its true completeness."""
        if snapshot is None:
            return
        identities = [
            SocketIdentity(
                protocol=s.protocol,
                local_address=s.local_address or "",
                local_port=s.local_port or 0,
                uid=s.uid,
            )
            for s in snapshot.sockets
            if s.local_address and s.local_port
        ]
        from .completeness import socket_table_completeness

        self.record(
            CATEGORY_SOCKET,
            socket_table_completeness(snapshot),
            identities,
            timestamp=snapshot.timestamp,
        )

    def series(self, category: str) -> tuple[Observation, ...]:
        """The observation window for *category*, oldest first."""
        return tuple(self._series.get(category, ()))


def first_observed_by_key(
    series: Sequence[Observation],
    category: str,
) -> dict[str, float]:
    """First-observed (monotonic) timestamp per identity key, where known."""
    result: dict[str, float] = {}
    for obs in series:
        if obs.timestamp is None:
            continue
        for identity in obs.identities:
            key = _entity_key(category, identity)
            if key not in result:
                result[key] = obs.timestamp
    return result


__all__ = [
    "MIN_PERSISTENT_OBSERVATIONS",
    "STABILITY_CATEGORIES",
    "TRACKER_WINDOW",
    "ObservationTracker",
    "classify_entity_state",
    "first_observed_by_key",
    "stabilize_drift",
]