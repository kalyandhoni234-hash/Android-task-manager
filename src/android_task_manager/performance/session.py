"""Per-device performance session.

A :class:`PerformanceSession` is the analysis-scoped state for one connected
device. It deliberately reuses the existing
:class:`android_task_manager.history.session.SessionHistory` for the four
canonical live metrics (cpu/memory/battery/storage) — including its
device-scoped ``begin_session`` / ``clear`` reset semantics — and extends it
with a :class:`PerformanceWindow` for the new extended metrics (process count,
network throughput).

The session is the single object the GUI feeds from monitor snapshots. It
contains **no** timer, **no** ADB, **no** Qt: it is a pure aggregation sink
that the monitor's existing ``tick()`` pushes into.
"""

from __future__ import annotations

from ..history.session import (
    BATTERY_MAX_SAMPLES,
    CPU_MAX_SAMPLES,
    MEMORY_MAX_SAMPLES,
    METRIC_BATTERY,
    METRIC_CPU,
    METRIC_MEMORY,
    METRIC_STORAGE,
    STORAGE_MAX_SAMPLES,
    SessionHistory,
)
from .models import PerformanceMetric, PerformanceSample
from .window import PerformanceWindow

_EXTENDED_MAX_SAMPLES = 600


class PerformanceSession:
    """Bounded, per-device performance history for the analysis engine."""

    def __init__(
        self,
        cpu_max_samples: int = CPU_MAX_SAMPLES,
        memory_max_samples: int = MEMORY_MAX_SAMPLES,
        battery_max_samples: int = BATTERY_MAX_SAMPLES,
        storage_max_samples: int = STORAGE_MAX_SAMPLES,
        extended_max_samples: int = _EXTENDED_MAX_SAMPLES,
    ) -> None:
        self.canonical = SessionHistory(
            cpu_max_samples=cpu_max_samples,
            memory_max_samples=memory_max_samples,
            battery_max_samples=battery_max_samples,
            storage_max_samples=storage_max_samples,
        )
        self.extended = PerformanceWindow(
            max_samples=extended_max_samples,
            metrics=[
                PerformanceMetric.PROCESS_COUNT.value,
                PerformanceMetric.NETWORK_RX.value,
                PerformanceMetric.NETWORK_TX.value,
            ],
        )
        self.device_serial: str | None = None
        self.session_started_at: float | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin_session(
        self, device_serial: str | None, timestamp: float | None = None
    ) -> None:
        """Start (or restart) the session for a device.

        Resets every window so history never mixes two devices: a reconnect
        or a device switch must never inherit the previous device's data.
        """
        self.clear()
        self.device_serial = device_serial
        self.session_started_at = timestamp

    def clear(self) -> None:
        """Drop every sample (disconnect / new session)."""
        self.canonical.clear()
        self.extended.clear()
        self.device_serial = None
        self.session_started_at = None

    # ------------------------------------------------------------------
    # Recording (values are 0-100 percentages of the live snapshots)
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        cpu_used_percent: float | None,
        memory_used_percent: float | None,
        battery_level_percent: float | None,
        storage_used_percent: float | None,
        process_count: int | None = None,
        network_rx_bytes_per_s: float | None = None,
        network_tx_bytes_per_s: float | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Record one observation. Canonical metrics go to ``SessionHistory``;
        extended metrics go to the ``PerformanceWindow``. None values are
        skipped (never fabricated)."""
        self.canonical.record(
            cpu_used_percent=cpu_used_percent,
            memory_used_percent=memory_used_percent,
            battery_level_percent=battery_level_percent,
            storage_used_percent=storage_used_percent,
            timestamp=timestamp,
        )
        extended: dict[str, float] = {}
        if process_count is not None:
            extended[PerformanceMetric.PROCESS_COUNT.value] = float(process_count)
        if network_rx_bytes_per_s is not None:
            extended[PerformanceMetric.NETWORK_RX.value] = float(network_rx_bytes_per_s)
        if network_tx_bytes_per_s is not None:
            extended[PerformanceMetric.NETWORK_TX.value] = float(network_tx_bytes_per_s)
        if extended:
            ts = timestamp if timestamp is not None else 0.0
            self.extended.add(PerformanceSample(timestamp=ts, metrics=extended))

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def window_for(self, metric: str) -> PerformanceWindow:
        """The window that holds *metric* (extended) or a single-metric
        wrapper around the canonical history."""
        if metric in (
            METRIC_CPU,
            METRIC_MEMORY,
            METRIC_BATTERY,
            METRIC_STORAGE,
        ):
            wrapper = PerformanceWindow(max_samples=self.canonical.metric(metric).max_samples)
            for sample in self.canonical.metric(metric):
                wrapper.add(
                    PerformanceSample(
                        timestamp=sample.timestamp, metrics={metric: sample.value}
                    )
                )
            return wrapper
        return self.extended

    @property
    def is_empty(self) -> bool:
        return self.canonical.is_empty and self.extended.is_empty


__all__ = ["PerformanceSession"]
