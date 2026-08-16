"""Why-flagged evidence explanation tests.

No device required. Verifies the deterministic fact derivation: facts are
only present when the underlying data exists, facts carry traceable
references, stability wording reflects the classified state, and missing
inputs degrade honestly instead of failing or guessing.
"""

from __future__ import annotations

from android_task_manager.heuristics.models import SEVERITY_HIGH
from android_task_manager.investigation.explain import (
    entity_stability_for,
    explain_signal,
)
from android_task_manager.investigation.models import (
    FACT_BASELINE,
    FACT_NETWORK,
    FACT_PACKAGE,
    FACT_PROCESS,
    FACT_SIGNAL,
    ObservationState,
)
from android_task_manager.investigation.stability import (
    stabilize_drift,
)
from tests import investigation_fixtures as fx


def _explain(**overrides):
    baseline = fx.baseline_with_stable()
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP, fx.NEW_PROC),
        packages=(fx.package("com.example.newproc", 10200),),
        sockets=(fx.STABLE_SOCK, fx.NEW_SOCK),
    )
    drift = fx.drift_report(
        baseline,
        current,
        (
            fx.drift_event("process", "NEW", fx.NEW_PROC.process_name),
            fx.drift_event("socket", "NEW", "tcp:0.0.0.0:4444"),
        ),
    )
    signal = fx.signal(
        "NEW_PROCESS_WITH_ACTIVE_SOCKET",
        SEVERITY_HIGH,
        fx.NEW_PROC.process_name,
        "A new process is communicating over the network.",
        contributing_events=(fx.NEW_PROC.process_name, "tcp:0.0.0.0:4444"),
    )
    defaults = dict(
        signal=signal,
        baseline=baseline,
        current=current,
        drift=drift,
        processes=fx.process_snapshot(
            1.0,
            (
                fx.process_info(
                    18472, fx.NEW_PROC.process_name, 10200, ppid=754,
                    cpu_percent=3.5, memory_percent=1.2, state="R",
                ),
                fx.process_info(754, "system_server", 1000, ppid=1),
            ),
        ),
        network_investigation=fx.network_snapshot(
            1.0,
            (
                fx.socket_info(
                    "tcp", "0.0.0.0", 4444, state="LISTEN", uid=10200,
                    pid=18472,
                ),
            ),
            uid_packages={10200: ("com.example.newproc",)},
        ),
        audits=(),
    )
    defaults.update(overrides)
    return explain_signal(**defaults)


def test_baseline_fact_present_for_new_entity() -> None:
    explanation = _explain()
    baseline_facts = [
        f for f in explanation.facts
        if f.category == FACT_BASELINE and f.reference == fx.NEW_PROC.process_name
    ]
    assert baseline_facts
    assert any("newly observed" in f.text for f in baseline_facts)


def test_cpu_memory_facts_only_when_present() -> None:
    with_metrics = _explain()
    assert any(
        f.category == FACT_PROCESS and "CPU" in f.text for f in with_metrics.facts
    )
    assert any(
        f.category == FACT_PROCESS and "memory" in f.text.lower()
        for f in with_metrics.facts
    )
    without_metrics = _explain(processes=fx.process_snapshot(
        1.0, (fx.process_info(18472, fx.NEW_PROC.process_name, 10200),),
    ))
    assert not any(
        f.category == FACT_PROCESS and "CPU" in f.text for f in without_metrics.facts
    )


def test_pid_and_ppid_facts_only_when_present() -> None:
    with_tree = _explain()
    assert any(
        f.category == FACT_PROCESS and "PID" in f.text for f in with_tree.facts
    )
    assert any(
        f.category == FACT_PROCESS and "parent" in f.text.lower()
        for f in with_tree.facts
    )
    without_tree = _explain(processes=fx.process_snapshot(
        1.0, (fx.process_info(18472, fx.NEW_PROC.process_name, 10200, ppid=None),),
    ))
    assert not any(
        f.category == FACT_PROCESS and "parent" in f.text.lower()
        for f in without_tree.facts
    )


def test_listening_state_fact() -> None:
    explanation = _explain()
    listening = [
        f for f in explanation.facts
        if f.category == FACT_NETWORK and "LISTEN" in f.text
    ]
    assert listening
    assert listening[0].reference == "tcp:0.0.0.0:4444"


def test_severity_and_rule_facts() -> None:
    explanation = _explain()
    signal_facts = [f for f in explanation.facts if f.category == FACT_SIGNAL]
    assert any("HIGH" in f.text for f in signal_facts)
    # The rule id is the fact's reference (the traceable evidence key).
    assert any(f.reference == "NEW_PROCESS_WITH_ACTIVE_SOCKET" for f in signal_facts)


def test_package_facts_reflect_uid_attribution() -> None:
    explanation = _explain()
    package_facts = [f for f in explanation.facts if f.category == FACT_PACKAGE]
    assert any("com.example.newproc" in f.text for f in package_facts)


def test_stability_facts_reflect_classification() -> None:
    report = fx.new_process_report()
    stability = stabilize_drift(
        report,
        fx.baseline_with_stable(),
        fx.current_with_new_process(),
        series=fx.persistent_series(),
    )
    records = [record for r in stability.values() for record in r.entities]
    record = entity_stability_for(fx.NEW_PROC.process_name, records)
    assert record is not None
    assert record.state is ObservationState.PERSISTENT
    explanation = _explain(entity_stability=record)
    persistent_facts = [
        f for f in explanation.facts
        if f.category == FACT_BASELINE and "persisted" in f.text.lower()
    ]
    assert persistent_facts


def test_missing_inputs_degrade_gracefully() -> None:
    explanation = _explain(
        processes=None,
        network_investigation=None,
        audits=(),
        attribution=None,
        entity_stability=None,
    )
    assert explanation.headline == "A new process is communicating over the network."
    # Still explains the signal fact itself.
    assert any(f.category == FACT_SIGNAL for f in explanation.facts)
    # Never fabricates network facts.
    assert not any(
        f.category == FACT_NETWORK and "LISTEN" in f.text
        for f in explanation.facts
    )


def test_explanation_is_deterministic() -> None:
    first = _explain()
    second = _explain()
    assert first == second
    assert [f.text for f in first.facts] == [f.text for f in second.facts]