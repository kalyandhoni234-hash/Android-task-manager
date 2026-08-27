"""Phase 4 tests: explainable intelligence (pure, no Qt/ADB).

Covers baseline deviation, deterministic score, trend classification,
non-causal contributor ranking, explanation text, and the orchestrator
view_state wiring plus a safety/architecture assertion that the performance
layer introduces no new timers, polling or destructive capability.
"""

from __future__ import annotations

import pathlib

from android_task_manager.background.models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
)
from android_task_manager.performance import (
    Baseline,
    ContributorCandidate,
    Explanation,
    MetricDeviation,
    PerformanceScore,
    PerformanceViewState,
    compute_deviation,
    compute_score,
    rank_contributors,
)
from android_task_manager.performance.explanation import (
    build_explanation,
    build_recommendations,
)
from android_task_manager.performance.orchestrator import PerformanceOrchestrator
from android_task_manager.performance.trend import classify_trend

PERF_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "android_task_manager" / "performance"


def _baseline(median=50.0, p95=70.0, mean=50.0, stddev=5.0, count=10):
    return Baseline(
        metric="cpu", count=count, mean=mean, median=median, p95=p95,
        minimum=median - 10, maximum=median + 10, stddev=stddev, computed_at=0.0,
    )


# ----------------------------------------------------------------------
# Deviation
# ----------------------------------------------------------------------

def test_deviation_normal():
    d = compute_deviation(
        metric="cpu", label="CPU", current=52.0, baseline=_baseline(),
        warn=70.0, crit=90.0, higher_is_worse=True,
    )
    assert d.band == "NORMAL"
    assert d.sufficient is True
    assert d.absolute_delta is not None


def test_deviation_critical():
    d = compute_deviation(
        metric="cpu", label="CPU", current=95.0, baseline=_baseline(),
        warn=70.0, crit=90.0, higher_is_worse=True,
    )
    assert d.band == "CRITICAL"
    assert d.absolute_delta is not None and d.absolute_delta > 0


def test_deviation_insufficient_baseline_uses_thresholds():
    d = compute_deviation(
        metric="cpu", label="CPU", current=95.0, baseline=_baseline(count=1),
        warn=70.0, crit=90.0, higher_is_worse=True,
    )
    assert d.sufficient is False
    assert d.absolute_delta is None
    assert d.band == "CRITICAL"  # still classifiable from thresholds


def test_deviation_battery_lower_is_worse():
    d = compute_deviation(
        metric="battery", label="Battery", current=15.0,
        baseline=_baseline(median=50.0, p95=40.0),
        warn=50.0, crit=20.0, higher_is_worse=False,
    )
    assert d.band == "CRITICAL"
    assert d.absolute_delta is not None and d.absolute_delta < 0


def test_deviation_zero_median_no_percentage_divide_by_zero():
    d = compute_deviation(
        metric="cpu", label="CPU", current=0.0,
        baseline=_baseline(median=0.0, p95=5.0, stddev=1.0),
        warn=70.0, crit=90.0, higher_is_worse=True,
    )
    assert d.percentage_delta is None
    assert d.absolute_delta == 0.0


# ----------------------------------------------------------------------
# Score
# ----------------------------------------------------------------------

def _dev(metric, band):
    return MetricDeviation(
        metric=metric, label=metric, current=0.0, baseline_median=None,
        baseline_p95=None, baseline_mean=None, baseline_stddev=None,
        baseline_count=0, absolute_delta=None, percentage_delta=None,
        z_score=None, band=band, sufficient=False,
    )


def test_score_critical_and_elevated():
    deviations = {
        "cpu": _dev("cpu", "CRITICAL"),
        "memory": _dev("memory", "ELEVATED"),
        "storage": _dev("storage", "NORMAL"),
        "battery": _dev("battery", "NORMAL"),
        "process": _dev("process", "NORMAL"),
    }
    score = compute_score(deviations)
    assert isinstance(score, PerformanceScore)
    assert score.score == 63  # 100 -25 (cpu) -12 (memory)


def test_score_all_critical_is_zero():
    deviations = {k: _dev(k, "CRITICAL") for k in ("cpu", "memory", "storage", "battery", "process")}
    assert compute_score(deviations).score == 0


def test_score_all_normal_is_100():
    deviations = {k: _dev(k, "NORMAL") for k in ("cpu", "memory", "storage", "battery", "process")}
    assert compute_score(deviations).score == 100


# ----------------------------------------------------------------------
# Trend
# ----------------------------------------------------------------------

def test_trend_degrading():
    assert classify_trend([10, 20, 30, 40]) == "DEGRADING"


def test_trend_improving():
    assert classify_trend([40, 30, 20, 10]) == "IMPROVING"


def test_trend_stable():
    assert classify_trend([10, 11, 10, 11]) == "STABLE"


def test_trend_recovering():
    assert classify_trend([50, 40, 30, 20], recovering_reference=15) == "RECOVERING"


def test_trend_insufficient():
    assert classify_trend([10]) == "INSUFFICIENT_DATA"


# ----------------------------------------------------------------------
# Contributors (non-causal ranking)
# ----------------------------------------------------------------------

def _bg_snapshot():
    return BackgroundAppsSnapshot(
        timestamp=0.0,
        entries=[
            BackgroundAppEntry(
                package_name="com.example.heavy", label="Heavy App",
                uid=10001, pids=(1, 2), cpu_percent=40.0, memory_percent=20.0,
                memory_kb=200, state=BackgroundAppState.BACKGROUND,
            ),
            BackgroundAppEntry(
                package_name="com.example.light", label="Light App",
                uid=10002, pids=(3,), cpu_percent=2.0, memory_percent=1.0,
                memory_kb=10, state=BackgroundAppState.BACKGROUND,
            ),
        ],
    )


def test_rank_contributors_orders_by_load():
    contribs = rank_contributors(_bg_snapshot())
    assert len(contribs) == 2
    assert contribs[0].package == "com.example.heavy"
    assert contribs[0].confidence == 1.0
    assert isinstance(contribs[0].relevant_metric, str)


def test_rank_contributors_excludes():
    contribs = rank_contributors(
        _bg_snapshot(), excluded={"com.example.heavy"}
    )
    assert contribs[0].package == "com.example.light"


def test_rank_contributors_missing_label_not_fabricated():
    snap = BackgroundAppsSnapshot(
        timestamp=0.0,
        entries=[
            BackgroundAppEntry(
                package_name="com.example.unknown", label=None,
                uid=10003, pids=(9,), cpu_percent=30.0, memory_percent=10.0,
                memory_kb=100, state=BackgroundAppState.BACKGROUND,
            ),
        ],
    )
    contribs = rank_contributors(snap)
    assert contribs[0].label is None
    assert contribs[0].package == "com.example.unknown"


# ----------------------------------------------------------------------
# Explanation (non-causal text)
# ----------------------------------------------------------------------

def test_explanation_uses_no_causal_language():
    dev = compute_deviation(
        metric="cpu", label="CPU", current=95.0, baseline=_baseline(),
        warn=70.0, crit=90.0, higher_is_worse=True,
    )
    contribs = rank_contributors(_bg_snapshot())
    expl = build_explanation(
        metric="cpu", title="CPU pressure", deviation=dev,
        trend="DEGRADING", contributors=contribs,
    )
    assert isinstance(expl, Explanation)
    blob = (expl.interpretation + " " + " ".join(expl.recommendations)).lower()
    for banned in ("caused", "causing", "responsible", "definitely malicious", "force-stop", "kill"):
        assert banned not in blob, f"forbidden causal term: {banned}"


def test_build_recommendations_investigation_only():
    recs = build_recommendations("memory", ())
    assert recs
    assert recs[0].lower().startswith("inspect")


# ----------------------------------------------------------------------
# Orchestrator view_state wiring
# ----------------------------------------------------------------------

def _cpu(pct, ts=0.0):
    from android_task_manager.cpu.models import CPUSnapshot
    return CPUSnapshot(timestamp=ts, aggregate_utilization_percent=pct, cores=())


def test_view_state_includes_phase4_fields():
    o = PerformanceOrchestrator()
    o.begin_session("SERIAL", timestamp=0.0)
    for i in range(30):
        o.ingest(cpu=_cpu(95.0 + (i % 5), float(i)), timestamp=float(i))
    state = o.view_state()
    assert isinstance(state, PerformanceViewState)
    assert state.performance_score is not None
    assert state.metric_deviations["cpu"].band == "CRITICAL"
    assert state.trends["cpu"] in (
        "STABLE", "DEGRADING", "IMPROVING", "RECOVERING", "INSUFFICIENT_DATA",
    )
    assert len(state.explanations) >= 1
    assert state.explanations[0].metric == "cpu"
    assert len(state.investigation_recommendations) >= 1
    assert all(isinstance(c, ContributorCandidate) for c in state.contributors)


# ----------------------------------------------------------------------
# Safety / architecture: no new timers, polling, or destructive capability
# ----------------------------------------------------------------------

def test_performance_layer_introduces_no_forbidden_capability():
    forbidden = ("QTimer", "MonitorWorker", "import subprocess", "import adb")
    for path in PERF_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for token in forbidden:
            assert token.lower() not in lowered, f"{path.name} contains forbidden token {token}"
