"""Heuristics layer — explainable risk signals over baseline drift facts.

The diff engine (``baseline/``) reports facts only; this package applies a
small, fixed set of documented rules on top and produces
:class:`SuspiciousSignal` items with fixed severities (MEDIUM/HIGH) and
specific human-readable reasons. No scoring, no threat feeds, no alerting —
alerting is a separate future feature.
"""

from .evaluate import RULES, evaluate_heuristics
from .models import SEVERITY_HIGH, SEVERITY_MEDIUM, HeuristicReport, SuspiciousSignal
from .rules import (
    RULE_IDS,
    RuleFunction,
    rule_multiple_new_listening_sockets_same_process,
    rule_new_process_with_active_socket,
    rule_new_unclassified_package_with_new_process,
)

__all__ = [
    "RULES",
    "RULE_IDS",
    "RuleFunction",
    "SEVERITY_HIGH",
    "SEVERITY_MEDIUM",
    "HeuristicReport",
    "SuspiciousSignal",
    "evaluate_heuristics",
    "rule_multiple_new_listening_sockets_same_process",
    "rule_new_process_with_active_socket",
    "rule_new_unclassified_package_with_new_process",
]