"""Tests for the rule engine (Phase D).

Covers operator semantics, duration ("FOR") rules, cooldown suppression
(no storms / duplicates), unavailable metrics never firing, session
scoping of cooldowns, determinism and rule management.
"""

from __future__ import annotations

import pytest

from android_task_manager.history.session import SessionHistory
from android_task_manager.rules import (
    RULE_METRIC_BATTERY,
    RULE_METRIC_CPU,
    RULE_METRIC_MEMORY,
    RULE_METRIC_STORAGE,
    Rule,
    RuleEngine,
    RuleFire,
    RuleOperator,
    RuleSeverity,
)

CPU_HIGH = Rule(
    rule_id="cpu_high",
    metric=RULE_METRIC_CPU,
    operator=RuleOperator.GE,
    threshold=85.0,
    severity=RuleSeverity.WARNING,
    title="CPU utilization high",
    description="Aggregate CPU utilization reaches the high threshold.",
    cooldown=60.0,
)


def _session_with_cpu(*samples: tuple[float, float]) -> SessionHistory:
    """A session whose cpu history holds (value, timestamp) samples."""
    session = SessionHistory()
    session.begin_session("FAKE123")
    for value, timestamp in samples:
        session.record(
            cpu_used_percent=value,
            memory_used_percent=None,
            battery_level_percent=None,
            storage_used_percent=None,
            timestamp=timestamp,
        )
    return session


# ---------------------------------------------------------------------------
# Basic firing
# ---------------------------------------------------------------------------


def test_rule_fires_when_condition_met() -> None:
    session = _session_with_cpu((90.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    fires = engine.evaluate(session, now=10.0)
    assert len(fires) == 1
    fire = fires[0]
    assert isinstance(fire, RuleFire)
    assert fire.rule_id == "cpu_high"
    assert fire.value == 90.0
    assert fire.fired_at == 10.0
    assert "CPU utilization high" in fire.message


def test_rule_does_not_fire_below_threshold() -> None:
    session = _session_with_cpu((30.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    assert engine.evaluate(session, now=10.0) == ()


def test_unavailable_metric_never_fires() -> None:
    empty = SessionHistory()
    empty.begin_session("FAKE123")
    engine = RuleEngine((CPU_HIGH,))
    assert engine.evaluate(empty, now=10.0) == ()


def test_empty_history_never_fires_even_on_empty_snapshot() -> None:
    session = SessionHistory()
    engine = RuleEngine((CPU_HIGH,))
    assert engine.evaluate(session, now=10.0) == ()


# ---------------------------------------------------------------------------
# Operator semantics
# ---------------------------------------------------------------------------


def test_ge_includes_boundary() -> None:
    session = _session_with_cpu((85.0, 10.0))
    assert len(RuleEngine((CPU_HIGH,)).evaluate(session, now=10.0)) == 1


@pytest.mark.parametrize(
    ("operator", "value", "fires"),
    [
        (RuleOperator.GT, 15.0, False),
        (RuleOperator.GT, 15.1, True),
        (RuleOperator.LE, 15.0, True),
        (RuleOperator.LE, 15.01, False),
        (RuleOperator.LT, 15.0, False),
        (RuleOperator.LT, 14.9, True),
        (RuleOperator.EQ, 15.0, True),
        (RuleOperator.EQ, 15.1, False),
    ],
)
def test_operator_boundaries(operator: RuleOperator, value: float, fires: bool) -> None:
    rule = Rule(
        rule_id=f"op_{operator.value}",
        metric=RULE_METRIC_CPU,
        operator=operator,
        threshold=15.0,
        severity=RuleSeverity.INFO,
        title="op",
        description="op",
    )
    session = _session_with_cpu((value, 10.0))
    engine = RuleEngine((rule,))
    assert (len(engine.evaluate(session, now=10.0)) == 1) is fires


# ---------------------------------------------------------------------------
# Duration rules ("IF metric <op> threshold FOR duration")
# ---------------------------------------------------------------------------


def test_duration_rule_fires_after_sustained_span() -> None:
    rule = Rule(
        rule_id="cpu_sustained",
        metric=RULE_METRIC_CPU,
        operator=RuleOperator.GE,
        threshold=85.0,
        duration=30.0,
        severity=RuleSeverity.CRITICAL,
        title="CPU sustained",
        description="CPU high for 30 s.",
    )
    # Values must differ between samples — the history deduplicates
    # consecutive identical values by design.
    session = _session_with_cpu(
        (90.0, 0.0),
        (91.0, 10.0),
        (92.0, 20.0),
        (93.0, 31.0),
    )
    engine = RuleEngine((rule,))
    fires = engine.evaluate(session, now=31.0)
    assert len(fires) == 1
    assert fires[0].sustained_since == 0.0  # the run started at t=0


def test_duration_rule_does_not_fire_before_span_elapses() -> None:
    rule = Rule(
        rule_id="cpu_sustained",
        metric=RULE_METRIC_CPU,
        operator=RuleOperator.GE,
        threshold=85.0,
        duration=30.0,
        severity=RuleSeverity.CRITICAL,
        title="CPU sustained",
        description="CPU high for 30 s.",
    )
    session = _session_with_cpu(
        (90.0, 0.0),
        (91.0, 10.0),
        (92.0, 20.0),
        (93.0, 29.0),
    )
    engine = RuleEngine((rule,))
    assert engine.evaluate(session, now=29.0) == ()


def test_duration_rule_broken_by_dip() -> None:
    rule = Rule(
        rule_id="cpu_sustained",
        metric=RULE_METRIC_CPU,
        operator=RuleOperator.GE,
        threshold=85.0,
        duration=30.0,
        severity=RuleSeverity.CRITICAL,
        title="CPU sustained",
        description="CPU high for 30 s.",
    )
    session = _session_with_cpu(
        (90.0, 0.0),
        (10.0, 10.0),  # dip breaks the run
        (91.0, 20.0),
        (92.0, 31.0),
    )
    engine = RuleEngine((rule,))
    assert engine.evaluate(session, now=31.0) == ()


def test_duration_rule_with_lt_operator() -> None:
    rule = Rule(
        rule_id="battery_critical_sustained",
        metric=RULE_METRIC_BATTERY,
        operator=RuleOperator.LE,
        threshold=20.0,
        duration=60.0,
        severity=RuleSeverity.CRITICAL,
        title="Battery critical",
        description="Battery at/below 20% for 60 s.",
    )
    session = SessionHistory()
    session.begin_session("FAKE123")
    for value, timestamp in ((19.0, 0.0), (18.0, 30.0), (17.0, 61.0)):
        session.record(
            cpu_used_percent=None,
            memory_used_percent=None,
            battery_level_percent=value,
            storage_used_percent=None,
            timestamp=timestamp,
        )
    engine = RuleEngine((rule,))
    fires = engine.evaluate(session, now=61.0)
    assert len(fires) == 1
    assert fires[0].value == 17.0  # the latest sample


def test_instantaneous_rule_reports_last_timestamp() -> None:
    session = _session_with_cpu((90.0, 10.0), (91.0, 12.0))
    engine = RuleEngine((CPU_HIGH,))
    fires = engine.evaluate(session, now=12.0)
    assert fires[0].sustained_since == 12.0


# ---------------------------------------------------------------------------
# Cooldown — no storms, no duplicates
# ---------------------------------------------------------------------------


def test_cooldown_suppresses_repeated_firing() -> None:
    session = _session_with_cpu((90.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    assert len(engine.evaluate(session, now=10.0)) == 1
    assert engine.evaluate(session, now=20.0) == ()  # within cooldown
    assert engine.evaluate(session, now=30.0) == ()


def test_fires_again_after_cooldown_elapsed() -> None:
    session = _session_with_cpu((90.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    engine.evaluate(session, now=10.0)
    fires = engine.evaluate(session, now=10.0 + 60.0)
    assert len(fires) == 1
    assert fires[0].fired_at == 70.0


def test_polling_storm_produces_single_fire() -> None:
    session = _session_with_cpu((90.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    assert len(engine.evaluate(session, now=10.0)) == 1
    for tick in (10.1, 10.2, 10.3, 11.0, 12.0):
        assert engine.evaluate(session, now=tick) == ()


def test_different_rules_are_independent() -> None:
    memory_rule = Rule(
        rule_id="memory_high",
        metric=RULE_METRIC_MEMORY,
        operator=RuleOperator.GE,
        threshold=90.0,
        severity=RuleSeverity.WARNING,
        title="Memory high",
        description="Used memory high.",
        cooldown=60.0,
    )
    session = SessionHistory()
    session.begin_session("FAKE123")
    session.record(
        cpu_used_percent=90.0,
        memory_used_percent=95.0,
        battery_level_percent=None,
        storage_used_percent=None,
        timestamp=10.0,
    )
    engine = RuleEngine((CPU_HIGH, memory_rule))
    fires = engine.evaluate(session, now=10.0)
    assert {fire.rule_id for fire in fires} == {"cpu_high", "memory_high"}
    # Both are in cooldown now — repeated evaluation fires nothing.
    assert engine.evaluate(session, now=20.0) == ()


# ---------------------------------------------------------------------------
# Session scoping of cooldowns
# ---------------------------------------------------------------------------


def test_begin_session_resets_cooldowns() -> None:
    session = _session_with_cpu((90.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    engine.evaluate(session, now=10.0)
    engine.begin_session()
    fires = engine.evaluate(session, now=10.0)
    assert len(fires) == 1  # fresh session → fresh cooldown


# ---------------------------------------------------------------------------
# Management and determinism
# ---------------------------------------------------------------------------


def test_disabled_rule_never_fires() -> None:
    rule = Rule(
        rule_id="cpu_high",
        metric=RULE_METRIC_CPU,
        operator=RuleOperator.GE,
        threshold=85.0,
        severity=RuleSeverity.WARNING,
        title="CPU high",
        description="desc",
        enabled=False,
    )
    session = _session_with_cpu((90.0, 10.0))
    assert RuleEngine((rule,)).evaluate(session, now=10.0) == ()


def test_unsupported_metric_rejected() -> None:
    rule = Rule(
        rule_id="bad",
        metric="gpu",
        operator=RuleOperator.GE,
        threshold=1.0,
        severity=RuleSeverity.INFO,
        title="bad",
        description="bad",
    )
    with pytest.raises(ValueError):
        RuleEngine((rule,))


def test_add_and_remove_rules() -> None:
    engine = RuleEngine()
    engine.add_rule(CPU_HIGH)
    assert engine.rule("cpu_high") is CPU_HIGH
    engine.remove_rule("cpu_high")
    assert engine.rule("cpu_high") is None


def test_rules_in_registration_order() -> None:
    second = Rule(
        rule_id="storage_high",
        metric=RULE_METRIC_STORAGE,
        operator=RuleOperator.GE,
        threshold=90.0,
        severity=RuleSeverity.WARNING,
        title="Storage high",
        description="desc",
    )
    engine = RuleEngine((CPU_HIGH, second))
    assert [rule.rule_id for rule in engine.rules] == ["cpu_high", "storage_high"]


def test_evaluation_is_deterministic() -> None:
    session = _session_with_cpu((90.0, 10.0))
    engine = RuleEngine((CPU_HIGH,))
    first = engine.evaluate(session, now=10.0)
    second = RuleEngine((CPU_HIGH,)).evaluate(session, now=10.0)
    assert first == second
