"""Performance episodes (pure, Qt/ADB-free).

A :class:`PerformanceEpisode` is a *view* over the existing lifecycle
information (the :class:`~android_task_manager.performance.tracker.ConditionTracker`
active conditions) plus the historical samples already recorded in the
:class:`~android_task_manager.performance.session.PerformanceSession`. It does
not duplicate the tracker's lifecycle — it consumes it.

An episode groups **every overlapping performance condition** that belongs to
the same active pressure window (CPU + memory + … stay ONE episode), and
answers:

* who it is (deterministic ``episode_id``, e.g. ``P-001``) and its
  ``lifecycle`` (``STARTED`` → ``ACTIVE`` → ``RECOVERED``);
* when it started / recovered (``started_at`` / ``recovered_at``);
* whether it is still active (``recovered_at is None``);
* duration (recovered − started, or now − started for an active episode);
* which conditions and affected metrics participated (deterministic order);
* the highest severity observed during the episode (escalation retained);
* the peak observed value of the primary metric and when it occurred
  (from real samples);
* the observed baseline (device norm, when enough samples exist);
* the Phase 4 performance score at start / minimum / recovery (``None``
  when unavailable — never fabricated);
* the observed contributors and how consistently they appeared.

Everything is built from recorded data. A missing timestamp, a non-monotonic
timestamp, or an incomplete episode is handled defensively and never yields a
fabricated value or a negative duration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from ..background.models import BackgroundAppsSnapshot
from .baseline import BaselineCalculator
from .contributors import ContributorCandidate, rank_contributors
from .models import PerformanceEvidence


class EpisodeLifecycle(str, Enum):
    """Lifecycle of a grouped performance episode."""

    STARTED = "STARTED"
    ACTIVE = "ACTIVE"
    RECOVERED = "RECOVERED"


__all__ = [
    "ContributorCorrelation",
    "EpisodeLifecycle",
    "PerformanceEpisode",
    "build_episode",
    "build_grouped_episode",
    "correlate_contributors",
    "format_duration",
]

#: Which session window holds the samples for a condition metric.
_WINDOW_KEY = {
    "cpu": "cpu",
    "memory": "memory",
    "storage": "storage",
    "battery": "battery",
    "process": "process_count",
    "application": "process_count",
}

#: Whether a higher raw value is worse (battery is inverted: low is bad).
_HIGHER_IS_WORSE = {
    "cpu": True,
    "memory": True,
    "storage": True,
    "process": True,
    "application": True,
    "battery": False,
}


@dataclass(frozen=True)
class ContributorCorrelation:
    """How persistently one application was observed as a top contributor.

    Built by replaying the background-app snapshots recorded *during* the
    episode. ``samples_present`` is how many episode samples contained the app;
    ``times_top`` is how many of those had it ranked #1. This is correlation,
    never causality.
    """

    package: str
    label: str | None
    metric: str
    latest_value: float | None
    process_count: int | None
    samples_present: int
    samples_total: int
    times_top: int
    confidence: float


@dataclass(frozen=True)
class PerformanceEpisode:
    """One complete (or in-progress) performance incident.

    A grouped episode carries every overlapping condition of one pressure
    window: ``condition_keys`` / ``metrics`` list them in first-appearance
    order, ``severity`` is the highest level observed (escalation retained),
    ``lifecycle`` is ``STARTED``/``ACTIVE``/``RECOVERED``, and the score
    fields preserve the Phase 4 score trajectory (``None`` when unknown).

    The single-condition fields (``condition_key``/``metric``/``peak_*``/
    ``baseline_value``) describe the *primary* condition — the first that
    started — so existing per-metric comparisons keep working unchanged.
    """

    condition_key: str
    category: str
    severity: str
    metric: str
    started_at: float | None
    recovered_at: float | None
    peak_timestamp: float | None
    peak_value: float | None
    baseline_value: float | None
    duration: float | None
    is_active: bool
    evidence: tuple[PerformanceEvidence, ...]
    contributors: tuple[ContributorCandidate, ...]
    contributor_correlation: tuple[ContributorCorrelation, ...]
    #: Grouped-episode fields (Phase 5). All defaulted so existing
    #: single-condition construction sites remain valid.
    episode_id: str | None = None
    condition_keys: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    lifecycle: str | None = None
    score_at_start: int | None = None
    score_min: int | None = None
    score_at_recovery: int | None = None
    score_delta: int | None = None


def _window_key(metric: str) -> str:
    return _WINDOW_KEY.get(metric, metric)


def format_duration(seconds: float | None) -> str:
    """Render a duration as ``Nm Ns`` / ``Ns`` / ``—`` (never negative)."""
    if seconds is None or seconds < 0:
        return "—"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m {secs}s"


def _higher_is_worse(metric: str) -> bool:
    return _HIGHER_IS_WORSE.get(metric, True)


def _episode_samples(session, wkey: str, start: float | None, end: float | None):
    """(timestamp, value) pairs for *wkey* within [start, end] (inclusive)."""
    win = session.window_for(wkey)
    if win.is_empty or wkey not in win.metrics():
        return []
    out: list[tuple[float, float]] = []
    for s in win.iter_samples():
        ts = s.timestamp
        v = s.metrics.get(wkey)
        if ts is None or v is None:
            continue
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        out.append((ts, v))
    return out


def correlate_contributors(
    history_items: Sequence[tuple[float, BackgroundAppsSnapshot]],
    *,
    pressure_metrics: Sequence[str] = (),
    excluded: set[str] | None = None,
) -> tuple[ContributorCorrelation, ...]:
    """Rank how persistently each app appeared as a top contributor.

    *history_items* are ``(timestamp, snapshot)`` pairs recorded during the
    episode. ``times_top`` counts how often the app was ranked #1 across those
    snapshots; ``samples_present`` counts how often it appeared at all.
    """
    excluded = excluded or set()
    total = len(history_items)
    if total == 0:
        return ()
    present: dict[str, list] = {}  # package -> [present, times_top, latest]
    for _ts, snap in history_items:
        ranked = rank_contributors(
            snap, pressure_metrics=tuple(pressure_metrics), excluded=set(excluded)
        )
        if not ranked:
            continue
        top = ranked[0]
        for c in ranked:
            rec = present.get(c.package)
            if rec is None:
                present[c.package] = [0, 0, c]
            present[c.package][0] += 1
        present[top.package][1] += 1
    correlations: list[ContributorCorrelation] = []
    for _pkg, (present_count, times_top, latest) in present.items():
        value = (
            latest.cpu_percent
            if latest.relevant_metric == "cpu"
            else latest.memory_percent
        )
        correlations.append(
            ContributorCorrelation(
                package=latest.package,
                label=latest.label,
                metric=latest.relevant_metric,
                latest_value=value,
                process_count=latest.process_count,
                samples_present=present_count,
                samples_total=total,
                times_top=times_top,
                confidence=round(times_top / total, 4) if total else 0.0,
            )
        )
    correlations.sort(key=lambda c: (c.times_top, c.samples_present), reverse=True)
    return tuple(correlations)


def build_episode(
    *,
    condition_key: str,
    category: str,
    severity: str,
    metric: str,
    first_seen: float | None,
    last_seen: float | None,
    is_active: bool,
    current_time: float | None,
    session,
    background_history: Sequence[tuple[float, BackgroundAppsSnapshot]] = (),
    excluded: set[str] | None = None,
    evidence: tuple[PerformanceEvidence, ...] = (),
) -> PerformanceEpisode:
    """Build one episode from a tracked condition and the recorded samples."""
    wkey = _window_key(metric)
    higher = _higher_is_worse(metric)

    end = None if is_active else last_seen
    effective_end = end if end is not None else current_time

    samples = _episode_samples(session, wkey, first_seen, effective_end)

    peak_ts: float | None = None
    peak_val: float | None = None
    if samples:
        peak_ts, peak_val = (
            min(samples, key=lambda x: x[1])
            if not higher
            else max(samples, key=lambda x: x[1])
        )

    duration: float | None = None
    if first_seen is not None:
        if end is not None:
            if end >= first_seen:
                duration = end - first_seen
        elif current_time is not None and current_time >= first_seen:
            duration = current_time - first_seen

    baseline_value: float | None = None
    win = session.window_for(wkey)
    if not win.is_empty and wkey in win.metrics():
        try:
            baseline = BaselineCalculator.from_window(wkey, win)
            if baseline.count >= 2:
                baseline_value = baseline.median
        except ValueError:
            baseline_value = None

    pressure_metrics = (
        (metric,) if metric in ("cpu", "memory", "storage", "process") else ("process",)
    )
    in_window = [
        (ts, snap)
        for ts, snap in background_history
        if (first_seen is None or ts >= first_seen)
        and (effective_end is None or ts <= effective_end)
    ]
    snap = None
    if in_window:
        if peak_ts is not None:
            snap = min(in_window, key=lambda x: abs(x[0] - peak_ts))[1]
        else:
            snap = max(in_window, key=lambda x: x[0])[1]
    contributors = rank_contributors(
        snap, pressure_metrics=pressure_metrics, excluded=excluded or set()
    )
    correlation = correlate_contributors(
        in_window, pressure_metrics=pressure_metrics, excluded=excluded or set()
    )

    return PerformanceEpisode(
        condition_key=condition_key,
        category=category,
        severity=severity,
        metric=metric,
        started_at=first_seen,
        recovered_at=end,
        peak_timestamp=peak_ts,
        peak_value=peak_val,
        baseline_value=baseline_value,
        duration=duration,
        is_active=is_active,
        evidence=evidence,
        contributors=contributors,
        contributor_correlation=correlation,
    )


def _pressure_metric_names(metrics: Sequence[str]) -> tuple[str, ...]:
    """Map episode metrics onto the contributor-ranking pressure vocabulary."""
    mapped = {
        "cpu": "cpu",
        "memory": "memory",
        "storage": "storage",
        "process": "process",
        "application": "process",
    }
    ordered = dict.fromkeys(mapped.get(m, "process") for m in metrics)
    return tuple(ordered)


def build_grouped_episode(
    *,
    episode_id: str | None,
    condition_keys: Sequence[str],
    metrics: Sequence[str],
    severity: str,
    first_seen: float | None,
    last_seen: float | None,
    is_active: bool,
    current_time: float | None,
    session,
    background_history: Sequence[tuple[float, BackgroundAppsSnapshot]] = (),
    excluded: set[str] | None = None,
    evidence: tuple[PerformanceEvidence, ...] = (),
    lifecycle: str | None = None,
    score_at_start: int | None = None,
    score_min: int | None = None,
    score_at_recovery: int | None = None,
    contributors: tuple[ContributorCandidate, ...] = (),
) -> PerformanceEpisode:
    """Build one grouped episode from tracker aggregates + recorded samples.

    The primary condition (first key / first metric) drives the sample-derived
    fields (peak, baseline, duration) via :func:`build_episode`; contributor
    correlation is replayed across **all** episode pressure metrics. Score
    fields are passed through verbatim — missing values stay ``None``. When
    *contributors* (the tracker's per-tick accumulated ranking) is non-empty
    it is authoritative; otherwise :func:`build_episode`'s window-derived
    ranking is kept.
    """
    primary_metric = metrics[0] if metrics else "cpu"
    primary_key = condition_keys[0] if condition_keys else f"{primary_metric}:grouped"
    base = build_episode(
        condition_key=primary_key,
        category=(primary_key.split(":", 1)[0] if ":" in primary_key else primary_metric),
        severity=severity,
        metric=primary_metric,
        first_seen=first_seen,
        last_seen=last_seen,
        is_active=is_active,
        current_time=current_time,
        session=session,
        background_history=background_history,
        excluded=excluded,
        evidence=evidence,
    )
    effective_end = last_seen if not is_active else current_time
    in_window = [
        (ts, snap)
        for ts, snap in background_history
        if (first_seen is None or ts >= first_seen)
        and (effective_end is None or ts <= effective_end)
    ]
    correlation = correlate_contributors(
        in_window,
        pressure_metrics=_pressure_metric_names(metrics),
        excluded=excluded or set(),
    )
    score_delta = (
        score_at_recovery - score_at_start
        if score_at_recovery is not None and score_at_start is not None
        else None
    )
    return replace(
        base,
        episode_id=episode_id,
        condition_keys=tuple(condition_keys),
        metrics=tuple(metrics),
        lifecycle=lifecycle,
        contributor_correlation=correlation,
        contributors=contributors or base.contributors,
        score_at_start=score_at_start,
        score_min=score_min,
        score_at_recovery=score_at_recovery,
        score_delta=score_delta,
    )
