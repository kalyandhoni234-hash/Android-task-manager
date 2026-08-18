"""Rule engine — declarative, deterministic alerting over session history.

Rules are pure declarations (metric / operator / threshold / duration /
severity / cooldown) evaluated by the GUI-independent :class:`RuleEngine`
against the bounded session history. Firing respects the per-rule cooldown
(no storms, no duplicates) and is reset per session.
"""

from .engine import RuleEngine
from .models import (
    DEFAULT_COOLDOWN_SECONDS,
    RULE_METRIC_BATTERY,
    RULE_METRIC_CPU,
    RULE_METRIC_MEMORY,
    RULE_METRIC_STORAGE,
    SUPPORTED_METRICS,
    Rule,
    RuleFire,
    RuleOperator,
    RuleSeverity,
)

__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "RULE_METRIC_BATTERY",
    "RULE_METRIC_CPU",
    "RULE_METRIC_MEMORY",
    "RULE_METRIC_STORAGE",
    "Rule",
    "RuleEngine",
    "RuleFire",
    "RuleOperator",
    "RuleSeverity",
    "SUPPORTED_METRICS",
]
