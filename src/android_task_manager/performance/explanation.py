"""Explainable evidence + investigation recommendations (pure, Qt/ADB-free).

Builds structured, deterministic, traceable explanations for each active
performance condition, and the corresponding *investigation* recommendations.

Hard honesty rules (inherited from the whole performance layer):

* Every sentence is built only from the literal fields it is given
  (current value, baseline median/p95, delta, trend, contributor load).
* No causal claim is ever produced. Applications are described as "observed
  contributor" / "associated with the pressure window", never "caused" or
  "responsible for".
* Recommendations are investigation-oriented only. They name the existing,
  verified action vocabulary (e.g. "Inspect … details") and NEVER an automatic
  destructive action (``FORCE_STOP`` / ``DISABLE`` / ``UNINSTALL``). The v0.7
  action capability remains the sole gate for any actual action and is not
  invoked here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .contributors import ContributorCandidate
from .deviation import MetricDeviation


@dataclass(frozen=True)
class Explanation:
    """A structured, non-causal explanation of one active condition."""

    metric: str
    title: str
    observed: tuple[str, ...]
    interpretation: str
    contributors: tuple[ContributorCandidate, ...]
    recommendations: tuple[str, ...]


def _is_percent(metric: str) -> bool:
    return metric in ("cpu", "memory", "storage", "battery")


def _current_text(metric: str, deviation: MetricDeviation | None) -> str | None:
    if deviation is None or deviation.current is None:
        return None
    if metric == "process":
        return f"Process count: {deviation.current:.0f}"
    return f"{deviation.label}: {deviation.current:.1f}%"


def _contributor_detail(c: ContributorCandidate) -> str:
    name = c.label or c.package
    if c.relevant_metric == "cpu":
        value = c.cpu_percent
    else:
        value = c.memory_percent
    unit = "%" if c.relevant_metric != "process" else ""
    val_text = f"{value:.1f}{unit}" if value is not None else "—"
    return (
        f"{name} {c.relevant_metric}: {val_text} · "
        f"processes {c.process_count or 0}"
    )


_BASE_RECOMMENDATIONS = {
    "cpu": "Inspect processes and application CPU contribution.",
    "memory": "Inspect the top memory-contributing application.",
    "storage": "Inspect storage usage and available capacity.",
    "process": "Inspect the process list for unusually high process counts.",
    "battery": "Inspect battery drain sources.",
    "application": "Inspect the top observed application contributor.",
}


def build_explanation(
    *,
    metric: str,
    title: str,
    deviation: MetricDeviation | None,
    trend: str | None,
    contributors: Sequence[ContributorCandidate] = (),
) -> Explanation:
    """Build one deterministic, non-causal explanation for a condition."""
    observed: list[str] = []

    current = _current_text(metric, deviation)
    if current is not None:
        observed.append(current)

    if deviation is not None and deviation.sufficient:
        if deviation.baseline_median is not None:
            observed.append(f"Baseline median: {deviation.baseline_median:.1f}%")
        if deviation.baseline_p95 is not None:
            observed.append(f"Baseline p95: {deviation.baseline_p95:.1f}%")
        if deviation.absolute_delta is not None:
            direction = "above" if deviation.absolute_delta >= 0 else "below"
            observed.append(
                f"Current value: {deviation.absolute_delta:+.1f} percentage "
                f"points {direction} median"
            )
        if deviation.percentage_delta is not None:
            observed.append(
                f"Change vs baseline: {deviation.percentage_delta:+.1f}%"
            )

    if trend is not None:
        observed.append(f"Trend: {trend}")
    for c in contributors[:2]:
        observed.append(
            f"Top observed {c.relevant_metric} contributor: {c.label or c.package}"
        )
        observed.append(_contributor_detail(c))

    interpretation = _interpret(metric, deviation, trend)
    recommendations = build_recommendations(metric, contributors)
    return Explanation(
        metric=metric,
        title=title,
        observed=tuple(observed),
        interpretation=interpretation,
        contributors=tuple(contributors),
        recommendations=tuple(recommendations),
    )


def _interpret(
    metric: str, deviation: MetricDeviation | None, trend: str | None
) -> str:
    if deviation is None or not deviation.sufficient:
        return (
            "Insufficient baseline data to compare the current reading against "
            "the device's observed norm."
        )
    if deviation.absolute_delta is None:
        return "No deviation from the observed baseline could be computed."
    direction = "above" if deviation.absolute_delta >= 0 else "below"
    magnitude = "substantially" if abs(deviation.absolute_delta) >= 10 else "moderately"
    sentence = (
        f"{deviation.label} usage is {magnitude} {direction} the observed baseline"
    )
    trend_part = {
        "DEGRADING": "and has continued increasing during the current pressure window.",
        "RECOVERING": "and has begun decreasing after the recent peak.",
        "IMPROVING": "and has begun decreasing.",
        "STABLE": "with no clear recent change.",
        "INSUFFICIENT_DATA": "with insufficient data to assess recent change.",
    }.get(trend or "INSUFFICIENT_DATA", "with no clear recent change.")
    return sentence[0].upper() + sentence[1:] + " " + trend_part


def build_recommendations(
    metric: str,
    contributors: Sequence[ContributorCandidate] = (),
) -> tuple[str, ...]:
    """Investigation recommendations (never automatic destructive actions)."""
    if contributors:
        top = contributors[0]
        name = top.label or top.package
        return (f"Inspect {name} process/application details.",)
    base = _BASE_RECOMMENDATIONS.get(metric, _BASE_RECOMMENDATIONS["application"])
    return (base,)


__all__ = ["Explanation", "build_explanation", "build_recommendations"]
