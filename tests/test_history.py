"""Tests for the bounded historical metrics engine (Phase A).

Covers sampling, duplicate prevention, window bounds, session/device reset
and the deterministic statistics (min/max/avg/latest/trend, peak periods,
sustained-above evaluation). Pure — no Qt, no ADB.
"""

from __future__ import annotations

import pytest

from android_task_manager.history import (
    MetricHistory,
    SessionHistory,
    TrendDirection,
)

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def test_empty_history_has_no_stats() -> None:
    history = MetricHistory(max_samples=10)
    assert history.is_empty
    assert len(history) == 0
    assert history.latest() is None
    stats = history.stats()
    assert stats.count == 0
    assert stats.minimum is None
    assert stats.maximum is None
    assert stats.average is None
    assert stats.latest is None
    assert stats.trend is TrendDirection.INSUFFICIENT


def test_samples_are_recorded_in_order() -> None:
    history = MetricHistory(max_samples=10)
    history.add_sample(10.0, 1.0)
    history.add_sample(20.0, 2.0)
    history.add_sample(30.0, 3.0)
    assert [s.value for s in history] == [10.0, 20.0, 30.0]
    assert [s.timestamp for s in history] == [1.0, 2.0, 3.0]
    assert history.latest() == 30.0


def test_none_values_are_never_recorded() -> None:
    history = MetricHistory(max_samples=10)
    history.add_sample(None, 1.0)
    history.add_sample(50.0, 2.0)
    history.add_sample(None, 3.0)
    assert [s.value for s in history] == [50.0]
    assert history.stats().count == 1


def test_consecutive_duplicates_are_dropped() -> None:
    history = MetricHistory(max_samples=10)
    history.add_sample(50.0, 1.0)
    history.add_sample(50.0, 2.0)
    history.add_sample(60.0, 3.0)
    history.add_sample(60.0, 4.0)
    assert [s.value for s in history] == [50.0, 60.0]


def test_dedupe_can_be_disabled() -> None:
    history = MetricHistory(max_samples=10, dedupe=False)
    history.add_sample(50.0, 1.0)
    history.add_sample(50.0, 2.0)
    assert len(history) == 2


def test_repeated_same_value_is_not_a_duplicate() -> None:
    # 50 → 60 → 50 must record all three: only consecutive duplicates drop.
    history = MetricHistory(max_samples=10)
    for value, ts in ((50.0, 1.0), (60.0, 2.0), (50.0, 3.0)):
        history.add_sample(value, ts)
    assert len(history) == 3


def test_timestamp_defaults_to_monotonic_clock() -> None:
    history = MetricHistory(max_samples=10)
    history.add_sample(10.0)
    history.add_sample(20.0)
    first, second = list(history)
    assert second.timestamp >= first.timestamp


def test_invalid_window_size_rejected() -> None:
    with pytest.raises(ValueError):
        MetricHistory(max_samples=0)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_window_is_bounded() -> None:
    history = MetricHistory(max_samples=3)
    for ts in range(10):
        history.add_sample(float(ts), float(ts))
    assert [s.value for s in history] == [7.0, 8.0, 9.0]
    assert history.stats().count == 3


def test_resize_drops_oldest_samples() -> None:
    history = MetricHistory(max_samples=10)
    for ts in range(6):
        history.add_sample(float(ts), float(ts))
    history.resize(2)
    assert [s.value for s in history] == [4.0, 5.0]
    assert history.max_samples == 2


def test_clear_resets_window() -> None:
    history = MetricHistory(max_samples=10)
    history.add_sample(50.0, 1.0)
    history.clear()
    assert history.is_empty
    assert history.latest() is None


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_min_max_avg_latest() -> None:
    history = MetricHistory(max_samples=10)
    for value, ts in ((40.0, 1.0), (90.0, 2.0), (50.0, 3.0)):
        history.add_sample(value, ts)
    stats = history.stats()
    assert stats.minimum == 40.0
    assert stats.maximum == 90.0
    assert stats.average == pytest.approx(60.0)
    assert stats.latest == 50.0
    assert stats.first_timestamp == 1.0
    assert stats.last_timestamp == 3.0


def test_trend_insufficient_with_few_samples() -> None:
    history = MetricHistory(max_samples=10)
    for ts in range(3):
        history.add_sample(float(ts * 10), float(ts))
    assert history.stats().trend is TrendDirection.INSUFFICIENT


def test_trend_rising() -> None:
    history = MetricHistory(max_samples=10)
    for ts in range(8):
        history.add_sample(float(ts), float(ts))
    assert history.stats().trend is TrendDirection.RISING


def test_trend_falling() -> None:
    history = MetricHistory(max_samples=10)
    for ts in range(8):
        history.add_sample(float(20 - ts), float(ts))
    assert history.stats().trend is TrendDirection.FALLING


def test_trend_flat() -> None:
    history = MetricHistory(max_samples=10)
    # Small jitter around 50 — stays inside the 1% relative epsilon.
    for value, ts in (
        (50.0, 0.0),
        (50.2, 1.0),
        (50.1, 2.0),
        (50.3, 3.0),
        (50.2, 4.0),
        (50.4, 5.0),
        (50.1, 6.0),
        (50.3, 7.0),
    ):
        history.add_sample(value, ts)
    assert history.stats().trend is TrendDirection.FLAT


def test_peak_periods_ignores_short_runs() -> None:
    history = MetricHistory(max_samples=20)
    # Values: 10, 90, 20, 95, 96, 30 (threshold 90, min_samples 2)
    for value, ts in (
        (10.0, 1.0),
        (90.0, 2.0),
        (20.0, 3.0),
        (95.0, 4.0),
        (96.0, 5.0),
        (30.0, 6.0),
    ):
        history.add_sample(value, ts)
    periods = history.peak_periods(threshold=90.0, min_samples=2)
    assert len(periods) == 1
    period = periods[0]
    assert period.start_timestamp == 4.0
    assert period.end_timestamp == 5.0
    assert period.peak_value == 96.0
    assert period.sample_count == 2


def test_peak_periods_returns_multiple_runs() -> None:
    history = MetricHistory(max_samples=20)
    for value, ts in (
        (95.0, 1.0),
        (96.0, 2.0),
        (10.0, 3.0),
        (91.0, 4.0),
        (92.0, 5.0),
    ):
        history.add_sample(value, ts)
    periods = history.peak_periods(threshold=90.0, min_samples=2)
    assert len(periods) == 2


def test_peak_periods_empty_when_never_reached() -> None:
    history = MetricHistory(max_samples=10)
    history.add_sample(10.0, 1.0)
    history.add_sample(20.0, 2.0)
    assert history.peak_periods(threshold=90.0) == ()


def test_sustained_since_requires_continuous_run() -> None:
    history = MetricHistory(max_samples=20)
    for value, ts in (
        (20.0, 1.0),
        (90.0, 2.0),
        (91.0, 3.0),
        (92.0, 4.0),
        (30.0, 5.0),
    ):
        history.add_sample(value, ts)
    # Above 90 continuously from t=2 to t=4 → span 2.0; needs 3.0 → None.
    assert history.sustained_since(90.0, 3.0) is None
    # A dip at t=5 breaks any longer run from t=2.
    assert history.sustained_since(90.0, 2.0) is None


def test_sustained_since_returns_run_start() -> None:
    history = MetricHistory(max_samples=20)
    for value, ts in (
        (20.0, 1.0),
        (90.0, 2.0),
        (91.0, 3.0),
        (92.0, 4.0),
    ):
        history.add_sample(value, ts)
    assert history.sustained_since(90.0, 2.0) == 2.0
    assert history.sustained_since(90.0, 0.5) == 3.0  # span reached at t=3


# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------


def test_session_records_all_metrics() -> None:
    session = SessionHistory()
    session.record(
        cpu_used_percent=55.0,
        memory_used_percent=70.0,
        battery_level_percent=38.0,
        storage_used_percent=82.0,
        timestamp=1.0,
    )
    session.record(
        cpu_used_percent=60.0,
        memory_used_percent=72.0,
        battery_level_percent=37.0,
        storage_used_percent=83.0,
        timestamp=2.0,
    )
    stats = session.stats()
    assert stats.cpu.latest == 60.0
    assert stats.memory.average == pytest.approx(71.0)
    assert stats.battery.latest == 37.0
    assert stats.storage.maximum == 83.0


def test_session_none_values_leave_metric_empty() -> None:
    session = SessionHistory()
    session.record(
        cpu_used_percent=None,
        memory_used_percent=None,
        battery_level_percent=None,
        storage_used_percent=None,
        timestamp=1.0,
    )
    assert session.is_empty


def test_begin_session_resets_every_window() -> None:
    session = SessionHistory()
    session.record(
        cpu_used_percent=55.0,
        memory_used_percent=70.0,
        battery_level_percent=38.0,
        storage_used_percent=82.0,
        timestamp=1.0,
    )
    session.begin_session("FAKE123", timestamp=10.0)
    assert session.is_empty
    assert session.device_serial == "FAKE123"
    assert session.session_started_at == 10.0


def test_begin_session_switches_device_cleanly() -> None:
    session = SessionHistory()
    session.begin_session("DEVICE_A")
    session.record(
        cpu_used_percent=55.0,
        memory_used_percent=70.0,
        battery_level_percent=38.0,
        storage_used_percent=82.0,
        timestamp=1.0,
    )
    session.begin_session("DEVICE_B")
    assert session.device_serial == "DEVICE_B"
    assert session.is_empty  # device A's history never leaks into device B


def test_clear_resets_session_identity() -> None:
    session = SessionHistory()
    session.begin_session("FAKE123")
    session.clear()
    assert session.device_serial is None
    assert session.session_started_at is None


def test_metric_key_lookup() -> None:
    session = SessionHistory()
    session.record(
        cpu_used_percent=55.0,
        memory_used_percent=70.0,
        battery_level_percent=38.0,
        storage_used_percent=82.0,
        timestamp=1.0,
    )
    from android_task_manager.history import METRIC_CPU, METRIC_STORAGE

    assert session.metric(METRIC_CPU).latest() == 55.0
    assert session.metric(METRIC_STORAGE).latest() == 82.0
