"""Automation models — approved, bounded, loop-protected action execution.

Automation executes *recommendations* through the v0.7 action layer. The
engine is deliberately restrictive:

* nothing runs without explicit approval;
* destructive actions never run through automation, even after approval
  (approval gates *timing*, not *safety* — destructive operations are
  exclusively a user decision through the GUI action layer);
* every (action, target) pair has a cooldown after a run and a per-session
  execution budget — loop protection against restart-crash-restart cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AutomationStatus(Enum):
    """Lifecycle of one automation task."""

    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AutomationTask:
    """One automation task derived from a recommendation.

    ``task_id`` is a deterministic session-scoped ``A-###`` sequence.
    ``requested_at`` / ``approved_at`` / ``executed_at`` are monotonic
    timestamps; ``None`` means the step never happened.
    """

    task_id: str
    recommendation_id: str
    action: str
    target: str
    destructive: bool
    requested_at: float
    status: AutomationStatus = AutomationStatus.WAITING_APPROVAL
    approved_at: float | None = None
    executed_at: float | None = None
    message: str = ""


__all__ = ["AutomationStatus", "AutomationTask"]