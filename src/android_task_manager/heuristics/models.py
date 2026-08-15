"""Heuristics layer — data models for explainable risk signals.

This layer consumes the facts-only output of the baseline diff engine
(``baseline/diff.py``) and applies small, documented rules on top. Every
flagged combination of facts is a :class:`SuspiciousSignal` with a fixed
severity and a specific, human-readable reason — no scoring, no
machine-learning, no external threat feeds.

Severity vocabulary is deliberately small: v1 only distinguishes
``MEDIUM`` from ``HIGH``. The diff engine's ``INFO`` (every fact, judged)
and the future alerting tier (feature #6) are separate concerns.

Rules never claim certainty they do not have: a rule that needs a value
that is missing (``None``) or a category that was not fully verified
(``DriftReport.unverified_categories``) simply does not fire.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: Severity vocabulary of the heuristics layer (v1).
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"


@dataclass(frozen=True)
class SuspiciousSignal:
    """One flagged combination of drift facts, with an explainable reason."""

    #: Short stable identifier of the rule that fired, e.g.
    #: ``"NEW_PROCESS_WITH_ACTIVE_SOCKET"``.
    rule_id: str
    #: SEVERITY_MEDIUM or SEVERITY_HIGH — this layer never downgrades to
    #: INFO and never invents CRITICAL in v1.
    severity: str
    #: What the signal is about (a process/package name, a uid, ...).
    entity: str
    #: One-sentence, instance-specific human-readable explanation.
    reason: str
    #: Entity strings of the DriftEvents that fed this signal (traceability).
    contributing_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class HeuristicReport:
    """The outcome of running every heuristic rule over one drift report."""

    evaluated_at: datetime
    signals: tuple[SuspiciousSignal, ...] = ()
    #: rule_ids that were run — even when none fired, so a report can
    #: honestly say "3 rules checked, 0 fired".
    rules_applied: tuple[str, ...] = ()