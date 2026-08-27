"""Historical comparison for episodes (pure, Qt/ADB-free).

Compares an episode against the device's observed baseline and against other
*comparable* episodes recorded in the same session. It deliberately:

* exposes data sufficiency explicitly — it never pretends a short session is
  statistically equivalent to long-term history;
* marks cross-session history as ``HISTORICAL_DATA_INSUFFICIENT`` rather than
  fabricating a comparison;
* produces only non-causal statements ("reached a higher value than the
  observed baseline p95"), never a root-cause claim.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .baseline import Baseline
from .episodes import PerformanceEpisode, format_duration

#: Returned in place of a fabricated cross-session comparison.
INSUFFICIENT = "HISTORICAL_DATA_INSUFFICIENT"


@dataclass(frozen=True)
class HistoricalComparison:
    """Deterministic historical comparison for one episode."""

    sufficient: bool
    message: str
    baseline_available: bool
    comparable_episode_count: int
    current_vs_baseline_median_pp: float | None
    current_vs_baseline_p95_pp: float | None
    peak_vs_baseline_p95_pp: float | None
    current_duration: float | None
    previous_median_duration: float | None
    interpretation: str
    details: tuple[str, ...]


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def find_comparable(
    episodes: Sequence[PerformanceEpisode],
    *,
    metric: str,
    exclude: PerformanceEpisode | None = None,
) -> list[PerformanceEpisode]:
    """Recovered, completed episodes of the same metric (for duration stats)."""
    out: list[PerformanceEpisode] = []
    for e in episodes:
        if e is exclude:
            continue
        if e.metric != metric:
            continue
        if e.is_active:
            continue
        if e.duration is None:
            continue
        out.append(e)
    return out


def build_historical_comparison(
    *,
    episode: PerformanceEpisode,
    baseline: Baseline | None,
    comparable: Sequence[PerformanceEpisode] = (),
) -> HistoricalComparison:
    """Build the comparison for one episode against baseline + past episodes."""
    details: list[str] = []

    baseline_available = baseline is not None and baseline.count >= 2
    peak_vs_p95: float | None = None
    cur_vs_median: float | None = None
    cur_vs_p95: float | None = None
    if baseline_available and baseline is not None and episode.peak_value is not None:
        peak_vs_p95 = round(episode.peak_value - baseline.p95, 2)
        cur_vs_median = round(episode.peak_value - baseline.median, 2)
        cur_vs_p95 = round(episode.peak_value - baseline.p95, 2)
        details.append(f"Observed baseline p95: {baseline.p95:.1f}%")
        if peak_vs_p95 is not None:
            sign = "+" if peak_vs_p95 >= 0 else ""
            details.append(
                f"Episode peak vs baseline p95: {sign}{peak_vs_p95:.1f} pp"
            )
    else:
        details.append(INSUFFICIENT + " (baseline)")

    comp = list(comparable)
    prev_median: float | None = None
    if comp:
        prev_median = _median([e.duration for e in comp if e.duration is not None])
        details.append(f"Historical comparable episodes: {len(comp)}")
        if prev_median is not None:
            details.append(
                f"Previous comparable median duration: {format_duration(prev_median)}"
            )
            if episode.duration is not None:
                details.append(
                    f"Current episode duration: {format_duration(episode.duration)}"
                )
    else:
        details.append(INSUFFICIENT + " (comparable episodes)")

    # Non-causal interpretation.
    interpretation = _interpret(
        baseline_available, peak_vs_p95, comp, prev_median, episode.duration
    )

    sufficient = baseline_available and bool(comp)
    message = (
        "Comparison available (session-scoped)."
        if sufficient
        else INSUFFICIENT
    )

    return HistoricalComparison(
        sufficient=sufficient,
        message=message,
        baseline_available=baseline_available,
        comparable_episode_count=len(comp),
        current_vs_baseline_median_pp=cur_vs_median,
        current_vs_baseline_p95_pp=cur_vs_p95,
        peak_vs_baseline_p95_pp=peak_vs_p95,
        current_duration=episode.duration,
        previous_median_duration=prev_median,
        interpretation=interpretation,
        details=tuple(details),
    )


def _interpret(
    baseline_available: bool,
    peak_vs_p95: float | None,
    comparable: list[PerformanceEpisode],
    prev_median: float | None,
    duration: float | None,
) -> str:
    parts: list[str] = []
    if baseline_available and peak_vs_p95 is not None:
        if peak_vs_p95 >= 0:
            parts.append(
                "The episode peak reached or exceeded the observed baseline p95."
            )
        else:
            parts.append(
                "The episode peak remained below the observed baseline p95."
            )
    if comparable and prev_median is not None and duration is not None:
        if duration > prev_median:
            parts.append(
                "The episode lasted longer than the observed comparable episodes."
            )
        elif duration < prev_median:
            parts.append(
                "The episode lasted shorter than the observed comparable episodes."
            )
        else:
            parts.append(
                "The episode lasted about as long as the observed comparable episodes."
            )
    if not parts:
        return (
            "Insufficient historical data to compare this episode against the "
            "observed norm."
        )
    return " ".join(parts)


__all__ = [
    "HistoricalComparison",
    "INSUFFICIENT",
    "build_historical_comparison",
    "find_comparable",
]
