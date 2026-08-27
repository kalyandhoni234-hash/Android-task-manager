"""Grouped performance-episode tracking (pure, Qt/ADB-free).

The :class:`~android_task_manager.performance.tracker.ConditionTracker`
already collapses per-tick findings into per-condition lifecycles (STARTED /
throttled ACTIVE / RECOVERED). This module adds the *temporal grouping* on
top: every condition that becomes active while an episode is open joins that
episode, and the episode only closes when **all** of its member conditions
have recovered.

    ConditionTracker (per-condition lifecycle)
        ↓  TrackerStep transitions
    EpisodeTracker (grouping + ids + aggregates)   ← this module, NEW
        ↓
    PerformanceEpisode (frozen render model)

Semantics (deterministic, device-free):

* **Start** — the first condition transition opens episode ``P-001``.
* **Continuation** — while open, further conditions join; affected metrics
  accumulate in first-appearance order; severity escalates to the highest
  level observed; evidence accumulates under a bounded retention rule;
  contributors are refreshed from already-resolved snapshots (never wiped by
  a snapshot-less tick); score start/min are tracked from the Phase 4 score.
* **Recovery** — a member condition recovering removes it from membership;
  the episode closes (``RECOVERED``) only when membership is empty.
* **Non-overlap** — after closure the next condition starts a new episode;
  episodes are never merged across a closed window.
* **Deterministic ids** — ``P-001``, ``P-002``, … assigned per session and
  reset by :meth:`EpisodeTracker.reset` (device disconnect / session close).

This module imports no Qt bindings, no OS process-execution tools, no device
bridge, and no GUI module, and never performs identity resolution:
contributors arrive already ranked.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .contributors import ContributorCandidate
from .episodes import EpisodeLifecycle
from .models import PerformanceEvidence
from .tracker import ActiveCondition

#: Severity ordering reused from the diagnostics vocabulary (no new levels).
_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}

#: Bounded retention for accumulated per-episode evidence statements.
EVIDENCE_RETENTION = 24

#: Bounded retention for completed episodes available for review.
EPISODE_RETENTION = 20


@dataclass(frozen=True)
class EpisodeRecord:
    """Aggregated state of one episode (open or completed)."""

    episode_id: str
    started_at: float | None
    recovered_at: float | None
    condition_keys: tuple[str, ...]
    metrics: tuple[str, ...]
    severity: str
    evidence: tuple[PerformanceEvidence, ...]
    contributors: tuple[ContributorCandidate, ...]
    score_at_start: int | None = None
    score_min: int | None = None
    score_at_recovery: int | None = None


@dataclass(frozen=True)
class EpisodeUpdate:
    """What one :meth:`EpisodeTracker.update` produced.

    ``closed_record`` carries the final aggregate of the episode that closed
    this tick (exactly one per closure), so callers can announce the recovery
    without touching tracker internals.
    """

    opened: bool = False
    closed: bool = False
    closed_episode_id: str | None = None
    closed_record: EpisodeRecord | None = None


class _OpenEpisode:
    """Mutable builder for the single currently-open episode.

    ``condition_order`` / ``metrics`` record every condition *ever* seen in
    the episode, in first-appearance order — they are retained even after an
    individual condition recovers. Closure is driven by ``active_keys`` only.
    """

    def __init__(
        self,
        episode_id: str,
        first_condition: ActiveCondition,
        now: float,
        score: int | None,
    ) -> None:
        self.episode_id = episode_id
        self.started_at = now
        #: Fixed at open time: drives sample-derived fields at render.
        self.primary_key = first_condition.key
        self.primary_metric = first_condition.metric
        self.condition_order: list[str] = [first_condition.key]
        self.metrics: list[str] = [first_condition.metric]
        self.active_keys: set[str] = {first_condition.key}
        self.severity: str = first_condition.finding.severity.value[1]
        self.evidence_ids: set[str] = set()
        self.evidence: list[PerformanceEvidence] = []
        self.contributors: tuple[ContributorCandidate, ...] = ()
        self.score_at_start = score
        self.score_min = score
        #: True only on the tick that opened the episode (STARTED vs ACTIVE).
        self.just_opened = True

    def absorb(self, condition: ActiveCondition) -> None:
        if condition.key not in self.condition_order:
            self.condition_order.append(condition.key)
        if condition.metric not in self.metrics:
            self.metrics.append(condition.metric)
        self.active_keys.add(condition.key)
        rank = _SEVERITY_RANK.get(condition.finding.severity.value[1], 0)
        current = _SEVERITY_RANK.get(self.severity, 0)
        if rank > current:
            self.severity = condition.finding.severity.value[1]

    def add_evidence(self, evidence: Sequence[PerformanceEvidence]) -> None:
        for item in evidence:
            if item.evidence_id in self.evidence_ids:
                continue
            self.evidence_ids.add(item.evidence_id)
            self.evidence.append(item)
        if len(self.evidence) > EVIDENCE_RETENTION:
            dropped = len(self.evidence) - EVIDENCE_RETENTION
            self.evidence = self.evidence[dropped:]

    def update_score(self, score: int | None) -> None:
        if score is None:
            return
        if self.score_min is None or score < self.score_min:
            self.score_min = score

    def release(self, key: str) -> None:
        self.active_keys.discard(key)

    @property
    def is_empty(self) -> bool:
        return not self.active_keys

    def to_record(self, *, recovered_at: float | None) -> EpisodeRecord:
        return EpisodeRecord(
            episode_id=self.episode_id,
            started_at=self.started_at,
            recovered_at=recovered_at,
            condition_keys=tuple(self.condition_order),
            metrics=tuple(self.metrics),
            severity=self.severity,
            evidence=tuple(self.evidence),
            contributors=self.contributors,
            score_at_start=self.score_at_start,
            score_min=self.score_min,
            score_at_recovery=None,
        )


@dataclass
class _ClosedEpisode:
    record: EpisodeRecord
    #: Insertion order counter for deterministic newest-first rendering.


class EpisodeTracker:
    """Groups condition lifecycles into bounded, deterministic episodes.

    Pure domain component: it consumes the already-normalized
    :class:`~android_task_manager.performance.tracker.TrackerStep` transitions
    each monitor tick and owns no timer, no ADB connection, no Qt object and
    no identity resolution.
    """

    def __init__(self) -> None:
        self._counter = 0
        self._open: _OpenEpisode | None = None
        self._completed: list[_ClosedEpisode] = []

    # ------------------------------------------------------------------
    # Tick input
    # ------------------------------------------------------------------

    def update(
        self,
        *,
        started: Sequence[ActiveCondition],
        recovered: Sequence[ActiveCondition],
        now: float,
        score: int | None = None,
        evidence: Sequence[PerformanceEvidence] = (),
        contributors: tuple[ContributorCandidate, ...] = (),
    ) -> EpisodeUpdate:
        """Apply one tick's condition transitions.

        ``started`` / ``recovered`` come straight from the ConditionTracker's
        ``TrackerStep``; ``score`` is the Phase 4 performance score for this
        tick (or ``None``); ``evidence`` / ``contributors`` are this tick's
        observations, consumed as-is.
        """
        opened = False
        closed = False
        closed_id: str | None = None

        for cond in started:
            if self._open is None:
                self._counter += 1
                self._open = _OpenEpisode(self._next_id(), cond, now, score)
                opened = True
            else:
                self._open.absorb(cond)
                self._open.update_score(score)

        if self._open is not None:
            self._open.just_opened = opened
            for cond in recovered:
                self._open.release(cond.key)
            if not started:
                self._open.update_score(score)
            self._open.add_evidence(evidence)
            if contributors:
                self._open.contributors = tuple(contributors)

            if self._open.is_empty:
                record = self._close_record(
                    self._open.to_record(recovered_at=now), recovery_score=score
                )
                self._completed.append(_ClosedEpisode(record=record))
                if len(self._completed) > EPISODE_RETENTION:
                    dropped = len(self._completed) - EPISODE_RETENTION
                    self._completed = self._completed[dropped:]
                closed_id = record.episode_id
                closed = True
                self._open = None

        closed_record = record if closed else None
        return EpisodeUpdate(
            opened=opened,
            closed=closed,
            closed_episode_id=closed_id,
            closed_record=closed_record,
        )

    # ------------------------------------------------------------------
    # Rendering inputs
    # ------------------------------------------------------------------

    @property
    def has_open_episode(self) -> bool:
        return self._open is not None

    @property
    def open_just_started(self) -> bool:
        """Whether the open episode was opened on the most recent tick."""
        return self._open is not None and self._open.just_opened

    def open_record(self) -> EpisodeRecord | None:
        """Aggregate snapshot of the currently-open episode (if any)."""
        if self._open is None:
            return None
        return self._open.to_record(recovered_at=None)

    @property
    def completed_episodes(self) -> tuple[EpisodeRecord, ...]:
        """Completed episodes, oldest → newest (render newest-first)."""
        return tuple(entry.record for entry in self._completed)

    @property
    def episode_count(self) -> int:
        return len(self._completed) + (1 if self._open is not None else 0)

    def reset(self) -> None:
        """Drop all live episode state (device disconnect / session close).

        The deterministic id sequence restarts at ``P-001`` afterwards, so a
        reconnect can never resurrect or collide with stale episodes.
        """
        self._counter = 0
        self._open = None
        self._completed = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        return f"P-{self._counter:03d}"

    @staticmethod
    def _close_record(
        base: EpisodeRecord, *, recovery_score: int | None
    ) -> EpisodeRecord:
        return EpisodeRecord(
            episode_id=base.episode_id,
            started_at=base.started_at,
            recovered_at=base.recovered_at,
            condition_keys=base.condition_keys,
            metrics=base.metrics,
            severity=base.severity,
            evidence=base.evidence,
            contributors=base.contributors,
            score_at_start=base.score_at_start,
            score_min=base.score_min,
            score_at_recovery=recovery_score,
        )


__all__ = [
    "EVIDENCE_RETENTION",
    "EPISODE_RETENTION",
    "EpisodeLifecycle",
    "EpisodeRecord",
    "EpisodeTracker",
    "EpisodeUpdate",
]
