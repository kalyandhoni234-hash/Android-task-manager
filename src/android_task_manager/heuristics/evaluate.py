"""Heuristics evaluation entry point.

Runs every registered rule (:data:`RULES`) over one drift report plus its
source snapshots and collects the fired :class:`SuspiciousSignal` objects
into a single :class:`HeuristicReport`. Pure function: no I/O, no ADB, no
side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..baseline.models import BaselineSnapshot, DriftReport
from .models import SEVERITY_HIGH, HeuristicReport, SuspiciousSignal
from .rules import (
    RULE_IDS,
    RuleFunction,
    rule_multiple_new_listening_sockets_same_process,
    rule_new_process_with_active_socket,
    rule_new_unclassified_package_with_new_process,
)

#: The full v1 rule set, in a fixed order (auditability: "3 rules checked").
RULES: tuple[RuleFunction, ...] = (
    rule_new_process_with_active_socket,
    rule_new_unclassified_package_with_new_process,
    rule_multiple_new_listening_sockets_same_process,
)

#: Sort order for signals: HIGH before MEDIUM, then rule_id, then entity.
_SEVERITY_RANK = {SEVERITY_HIGH: 0, "MEDIUM": 1}


def evaluate_heuristics(
    report: DriftReport,
    baseline: BaselineSnapshot,
    current: BaselineSnapshot,
    *,
    evaluated_at: datetime | None = None,
) -> HeuristicReport:
    """Run every rule in :data:`RULES` and return the combined report.

    ``rules_applied`` lists every rule's id — fired or not — so an empty
    ``signals`` tuple honestly means "checked, nothing fired".
    """
    signals: list[SuspiciousSignal] = []
    for rule in RULES:
        signals.extend(rule(report, baseline, current))
    signals.sort(key=lambda signal: (_severity_rank(signal.severity), signal.rule_id, signal.entity))
    return HeuristicReport(
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        signals=tuple(signals),
        rules_applied=tuple(RULE_IDS[rule] for rule in RULES),
    )


def _severity_rank(severity: str) -> int:
    """Order severities by importance (HIGH first); unknown sorts last."""
    if severity == SEVERITY_HIGH:
        return 0
    if severity == "MEDIUM":
        return 1
    return 2