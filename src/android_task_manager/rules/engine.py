"""Rule engine — deterministic evaluation of declarative alerting rules.

Pure and GUI-independent: evaluation consumes the session history
(bounded metric windows) and produces ``RuleFire`` results.

Invariants:

* **Never guess** — a metric with no samples (unavailable) never fires
  and never produces an error; the rule is simply not evaluated.
* **Duration semantics** — a rule with ``duration`` fires only when the
  condition held continuously for that span (the walk goes backwards
  from the latest sample; a single dip breaks the run).
* **No storms, no duplicates** — the cooldown suppresses repeated
  firings of the same rule; consecutive identical metric values are
  already deduplicated by the history window.
* **Session scoping** — cooldown state belongs to one session; starting
  a new session resets it, so a rule can fire again immediately after a
  reconnect.
* **Deterministic** — evaluation is a pure function of the history and
  the explicit ``now`` timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..history.metrics import MetricHistory
from ..history.session import SessionHistory
from .models import (
    SUPPORTED_METRICS,
    Rule,
    RuleFire,
    RuleOperator,
)

#: Operators where the threshold boundary is inclusive (value == threshold
#: satisfies the condition). The canonical metrics classify with the same
#: boundary semantics (>= high, > elevated).
_INCLUSIVE_OPERATORS = (RuleOperator.GE, RuleOperator.LE, RuleOperator.EQ)


def _compare(operator: RuleOperator, value: float, threshold: float) -> bool:
    """The operator predicate on a single value."""
    if operator is RuleOperator.GE:
        return value >= threshold
    if operator is RuleOperator.GT:
        return value > threshold
    if operator is RuleOperator.LE:
        return value <= threshold
    if operator is RuleOperator.LT:
        return value < threshold
    return value == threshold


def _satisfied(rule: Rule, history: MetricHistory, now: float) -> float | None:
    """The sustained-since timestamp when *rule* holds on *history*, or
    None when the condition is not (yet) met."""
    if rule.duration is not None:
        return history.sustained_while(
            lambda value: _compare(rule.operator, value, rule.threshold),
            rule.duration,
        )
    latest = history.latest()
    if latest is None:
        return None
    if not _compare(rule.operator, latest, rule.threshold):
        return None
    return history.last_timestamp()


@dataclass(frozen=True)
class _RuleState:
    """Per-rule evaluation state within one session."""

    last_fired_at: float | None = None


class RuleEngine:
    """Evaluates a fixed set of rules against the session history."""

    def __init__(self, rules: tuple[Rule, ...] | list[Rule] = ()) -> None:
        self._rules: dict[str, Rule] = {}
        self._states: dict[str, _RuleState] = {}
        for rule in rules:
            self.add_rule(rule)

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: Rule) -> None:
        """Register *rule* (validates the metric key)."""
        if rule.metric not in SUPPORTED_METRICS:
            raise ValueError(f"unsupported rule metric: {rule.metric}")
        self._rules[rule.rule_id] = rule
        self._states.setdefault(rule.rule_id, _RuleState())

    def remove_rule(self, rule_id: str) -> None:
        """Unregister a rule (unknown ids are ignored)."""
        self._rules.pop(rule_id, None)
        self._states.pop(rule_id, None)

    def rule(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    @property
    def rules(self) -> tuple[Rule, ...]:
        """Registered rules in registration order."""
        return tuple(self._rules.values())

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def begin_session(self) -> None:
        """Reset evaluation state (cooldowns) for a new session."""
        self._states = {rule_id: _RuleState() for rule_id in self._rules}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self, session: SessionHistory, now: float
    ) -> tuple[RuleFire, ...]:
        """Evaluate every enabled rule against *session* at *now*.

        Returns the rules that fired, in registration order. A rule fires
        when its condition holds and its cooldown has elapsed since its
        last firing (or it never fired this session).
        """
        fires: list[RuleFire] = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            state = self._states[rule.rule_id]
            if state.last_fired_at is not None:
                if now - state.last_fired_at < rule.cooldown:
                    continue
            sustained = _satisfied(rule, session.metric(rule.metric), now)
            if sustained is None:
                continue
            value = session.metric(rule.metric).latest()
            if value is None:
                continue
            self._states[rule.rule_id] = _RuleState(last_fired_at=now)
            fires.append(
                RuleFire(
                    rule_id=rule.rule_id,
                    fired_at=now,
                    value=value,
                    sustained_since=sustained,
                    message=(
                        f"{rule.title}: {value:.0f}% {rule.operator.value} "
                        f"{rule.threshold:g}%"
                    ),
                )
            )
        return tuple(fires)


__all__ = ["RuleEngine", "_compare", "_satisfied"]