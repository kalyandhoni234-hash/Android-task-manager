"""Rule engine models — declarative, deterministic alerting rules.

A rule is a pure declaration: a canonical metric key, a comparison
operator, a threshold, an optional duration ("IF metric <op> threshold
FOR duration"), a severity and a cooldown. The engine that evaluates
rules lives in ``engine.py``; nothing here touches a GUI or a device.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Canonical metric keys a rule can target (lockstep with history/).
RULE_METRIC_CPU = "cpu"
RULE_METRIC_MEMORY = "memory"
RULE_METRIC_BATTERY = "battery"
RULE_METRIC_STORAGE = "storage"

#: Canonical metric keys supported by the rule engine.
SUPPORTED_METRICS = (
    RULE_METRIC_CPU,
    RULE_METRIC_MEMORY,
    RULE_METRIC_BATTERY,
    RULE_METRIC_STORAGE,
)

#: Default minimum time between two firings of the same rule (seconds).
DEFAULT_COOLDOWN_SECONDS = 60.0


class RuleOperator(Enum):
    """Comparison operators for rule thresholds."""

    GE = ">="
    GT = ">"
    LE = "<="
    LT = "<"
    EQ = "=="


class RuleSeverity(Enum):
    """Severity of a fired rule (lockstep with the timeline vocabulary)."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Rule:
    """One declarative alerting rule.

    * ``rule_id`` — a stable, unique key ("cpu_sustained_high").
    * ``metric`` — one of the canonical metric keys.
    * ``operator`` / ``threshold`` — the condition on the metric value.
    * ``duration`` — when set, the condition must hold continuously for
      this long (same time units as the sample timestamps) before the
      rule fires; ``None`` means "fires on the first qualifying sample".
    * ``cooldown`` — minimum time between two firings (no storm, no
      duplicate alerts for the same condition).
    * ``severity`` / ``title`` / ``description`` — presentation.
    """

    rule_id: str
    metric: str
    operator: RuleOperator
    threshold: float
    severity: RuleSeverity
    title: str
    description: str
    duration: float | None = None
    cooldown: float = DEFAULT_COOLDOWN_SECONDS
    enabled: bool = True


@dataclass(frozen=True)
class RuleFire:
    """The result of one rule firing."""

    rule_id: str
    fired_at: float
    value: float
    sustained_since: float | None = None
    message: str = ""


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "RULE_METRIC_BATTERY",
    "RULE_METRIC_CPU",
    "RULE_METRIC_MEMORY",
    "RULE_METRIC_STORAGE",
    "Rule",
    "RuleFire",
    "RuleOperator",
    "RuleSeverity",
    "SUPPORTED_METRICS",
]