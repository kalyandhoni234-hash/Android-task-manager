"""Structured investigation summary for one episode (pure, Qt/ADB-free).

Consumes a :class:`~android_task_manager.performance.episodes.PerformanceEpisode`,
its baseline :class:`~android_task_manager.performance.deviation.MetricDeviation`,
and the
:class:`~android_task_manager.performance.history_compare.HistoricalComparison`
to produce one deterministic, fully-traceable investigation summary.

Every statement is built only from the literal episode fields. No causal claim
("caused", "responsible for") is ever produced; applications are described as
"repeatedly observed as the top contributor". Recommendations are
investigation-only and never an automatic destructive action.
"""

from __future__ import annotations

from dataclasses import dataclass

from .deviation import MetricDeviation
from .episodes import (
    ContributorCorrelation,
    PerformanceEpisode,
    format_duration,
)
from .history_compare import HistoricalComparison


@dataclass(frozen=True)
class InvestigationSummary:
    """One structured investigation summary for an episode."""

    condition: str
    metric: str
    status: str
    started_at: float | None
    recovered_at: float | None
    duration_text: str
    peak: float | None
    baseline: float | None
    peak_vs_baseline_pp: float | None
    trend: str | None
    top_contributor: ContributorCorrelation | None
    historical: HistoricalComparison
    evidence_bullets: tuple[str, ...]
    recommendation: str
    is_active: bool


def build_investigation_summary(
    *,
    episode: PerformanceEpisode,
    deviation: MetricDeviation | None,
    historical: HistoricalComparison,
    top_correlation: ContributorCorrelation | None = None,
    trend: str | None = None,
    recommendation: str = "",
) -> InvestigationSummary:
    """Build a deterministic, non-causal investigation summary."""
    status = "ACTIVE" if episode.is_active else "RECOVERED"
    peak = episode.peak_value
    baseline = episode.baseline_value

    peak_vs_baseline: float | None = None
    if peak is not None and baseline is not None:
        peak_vs_baseline = round(peak - baseline, 2)

    bullets: list[str] = []
    is_percent = episode.metric in ("cpu", "memory", "storage", "battery")
    if peak is not None:
        bullets.append(
            f"The condition reached {peak:.1f}%."
            if is_percent
            else f"The condition reached {peak:.0f}."
        )
    if baseline is not None and peak is not None and peak_vs_baseline is not None:
        sign = "+" if peak_vs_baseline >= 0 else ""
        bullets.append(
            f"Peak was {sign}{peak_vs_baseline:.1f} pp above the observed baseline "
            f"of {baseline:.1f}%."
        )
    if deviation is not None and deviation.sufficient:
        if deviation.absolute_delta is not None:
            direction = "above" if deviation.absolute_delta >= 0 else "below"
            bullets.append(
                f"Usage was {direction} the observed baseline during the episode."
            )
    if trend is not None:
        bullets.append(f"Trend: {trend}.")

    if top_correlation is not None and top_correlation.times_top > 0:
        name = top_correlation.label or top_correlation.package
        bullets.append(
            f"{name} was repeatedly observed as the top {top_correlation.metric} "
            f"contributor in {top_correlation.times_top}/"
            f"{top_correlation.samples_total} episode samples."
        )

    return InvestigationSummary(
        condition=episode.condition_key,
        metric=episode.metric,
        status=status,
        started_at=episode.started_at,
        recovered_at=episode.recovered_at,
        duration_text=format_duration(episode.duration),
        peak=peak,
        baseline=baseline,
        peak_vs_baseline_pp=peak_vs_baseline,
        trend=trend,
        top_contributor=top_correlation,
        historical=historical,
        evidence_bullets=tuple(bullets),
        recommendation=recommendation,
        is_active=episode.is_active,
    )


__all__ = ["InvestigationSummary", "build_investigation_summary"]
