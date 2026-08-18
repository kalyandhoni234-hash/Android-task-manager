"""Recommendation models — deterministic, evidence-derived suggestions.

A recommendation is the "observation → finding → recommendation → action"
chain: it references the finding (or fired rule) that produced it, carries
a deterministic rationale, and — when a concrete, validated action exists —
names the canonical action and its validated target.

Destructive actions (force-stop and above, per the action layer) are
carried so the user/automation can *consider* them, but they are never
``automation_allowed``: automation may only run non-destructive
recommendations, and even those require explicit approval (Phase F).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Severity vocabulary for recommendations (lockstep with health/timeline).
RECOMMENDATION_SEVERITY_INFO = "info"
RECOMMENDATION_SEVERITY_WARNING = "warning"
RECOMMENDATION_SEVERITY_CRITICAL = "critical"

_RECOMMENDATION_SEVERITIES = (
    RECOMMENDATION_SEVERITY_INFO,
    RECOMMENDATION_SEVERITY_WARNING,
    RECOMMENDATION_SEVERITY_CRITICAL,
)


@dataclass(frozen=True)
class Recommendation:
    """One deterministic recommendation derived from collected evidence.

    * ``recommendation_id`` — stable, deterministic sequence id.
    * ``finding_ref`` — the finding (title) or rule id that produced it.
    * ``action`` — a canonical action name from the action layer, or None
      for informational recommendations (nothing is ever guessed).
    * ``target`` — the validated package name the action would apply to,
      or None.
    * ``destructive`` — True when the action belongs to the destructive
      set (explicit user approval always required).
    * ``automation_allowed`` — True only for non-destructive actions;
      automation must still obtain approval before executing.
    """

    recommendation_id: str
    finding_ref: str
    title: str
    rationale: str
    severity: str
    action: str | None = None
    target: str | None = None
    destructive: bool = False
    automation_allowed: bool = False


__all__ = [
    "RECOMMENDATION_SEVERITY_CRITICAL",
    "RECOMMENDATION_SEVERITY_INFO",
    "RECOMMENDATION_SEVERITY_WARNING",
    "Recommendation",
]