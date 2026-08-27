"""Finding deduplication and condition lifecycle (pure, Qt-independent).

The analysis engine can flag the same sustained condition on every monitor
tick. Emitting one finding per tick would flood the UI and the timeline. This
module tracks *active conditions* across ticks and collapses them into a
single lifecycle:

* a condition appears  -> STARTED    (one finding is emitted)
* a condition persists -> ACTIVE     (throttled, never per-tick)
* a condition clears   -> RECOVERED

A condition's identity is a stable string key (e.g. ``"cpu:warning"`` or
``"app:com.example.heavy"``) supplied by the orchestrator, so identical
breaches across ticks are recognized as the *same* condition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..diagnostics.models import DiagnosticFinding


class ConditionPhase(str, Enum):
    """Lifecycle phase of a tracked performance condition."""

    STARTED = "started"
    ACTIVE = "active"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class ActiveCondition:
    """One currently (or just) active condition."""

    key: str
    finding: DiagnosticFinding
    metric: str
    first_seen: float
    last_seen: float


@dataclass(frozen=True)
class TrackerStep:
    """The lifecycle transitions produced by one ``update``."""

    started: tuple[ActiveCondition, ...] = ()
    recovered: tuple[ActiveCondition, ...] = ()
    active_persisted: tuple[ActiveCondition, ...] = ()


class ConditionTracker:
    """Tracks active conditions and emits lifecycle transitions.

    ``active_interval_s`` throttles ACTIVE emissions: an ACTIVE event is
    produced at most once per interval of monitor time while a condition
    holds, so a 30-tick breach does not generate 30 events.
    """

    def __init__(self, active_interval_s: float = 60.0) -> None:
        self._active_interval = active_interval_s
        self._active: dict[str, ActiveCondition] = {}
        self._last_active_emitted: dict[str, float] = {}

    #: ``conditions`` is ``(key, finding, metric)`` for every condition that
    #: is active *this* tick. ``now`` is the monitor timestamp.
    def update(
        self,
        conditions: list[tuple[str, DiagnosticFinding, str]],
        now: float,
    ) -> TrackerStep:
        current: dict[str, tuple[DiagnosticFinding, str]] = {
            key: (finding, metric) for key, finding, metric in conditions
        }
        started: list[ActiveCondition] = []
        recovered: list[ActiveCondition] = []
        active_persisted: list[ActiveCondition] = []

        # Recoveries: previously active, absent this tick.
        for key, cond in list(self._active.items()):
            if key not in current:
                recovered.append(cond)
                del self._active[key]
                self._last_active_emitted.pop(key, None)

        # Starts / ongoing.
        for key, (finding, metric) in current.items():
            existing = self._active.get(key)
            if existing is None:
                new = ActiveCondition(
                    key=key,
                    finding=finding,
                    metric=metric,
                    first_seen=now,
                    last_seen=now,
                )
                self._active[key] = new
                self._last_active_emitted[key] = now
                started.append(new)
            else:
                updated = ActiveCondition(
                    key=key,
                    finding=finding,
                    metric=metric,
                    first_seen=existing.first_seen,
                    last_seen=now,
                )
                self._active[key] = updated
                last = self._last_active_emitted.get(key, existing.first_seen)
                if now - last >= self._active_interval:
                    self._last_active_emitted[key] = now
                    active_persisted.append(updated)

        return TrackerStep(
            started=tuple(started),
            recovered=tuple(recovered),
            active_persisted=tuple(active_persisted),
        )

    def reset(self) -> None:
        """Drop every active condition (device disconnect / session close)."""
        self._active.clear()
        self._last_active_emitted.clear()

    @property
    def active_keys(self) -> tuple[str, ...]:
        return tuple(self._active)

    @property
    def active_conditions(self) -> tuple[ActiveCondition, ...]:
        """Currently active conditions (callers read ``finding`` for display)."""
        return tuple(self._active.values())


__all__ = [
    "ActiveCondition",
    "ConditionPhase",
    "ConditionTracker",
    "TrackerStep",
]
