"""Session-scoped historical metrics for the device intelligence engine.

Aggregates the four canonical live metrics (CPU utilization, memory used
percentage, battery level, storage used percentage) into bounded, per-session
histories. The session is device-scoped: starting a session (re)sets every
window so history never mixes two devices, and a device switch or disconnect
is an explicit reset — stale history is never presented as current.
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import MetricHistory, MetricStats

#: Retention defaults: each window is bounded by sample count, and the
#: samples arrive on the monitor's per-metric cadence (CPU 2 s, memory 10 s,
#: battery 15 s, storage 30 s), so the retention is a time-bounded window:
#: CPU ~6 min, memory ~20 min, battery ~24 min, storage ~30 min.
CPU_MAX_SAMPLES = 180
MEMORY_MAX_SAMPLES = 120
BATTERY_MAX_SAMPLES = 96
STORAGE_MAX_SAMPLES = 60

#: Canonical metric keys.
METRIC_CPU = "cpu"
METRIC_MEMORY = "memory"
METRIC_BATTERY = "battery"
METRIC_STORAGE = "storage"

_ALL_METRICS = (METRIC_CPU, METRIC_MEMORY, METRIC_BATTERY, METRIC_STORAGE)


@dataclass(frozen=True)
class SessionStats:
    """Statistics of every metric in a session history."""

    cpu: MetricStats
    memory: MetricStats
    battery: MetricStats
    storage: MetricStats


class SessionHistory:
    """Bounded histories of the four live metrics for one device session."""

    def __init__(
        self,
        cpu_max_samples: int = CPU_MAX_SAMPLES,
        memory_max_samples: int = MEMORY_MAX_SAMPLES,
        battery_max_samples: int = BATTERY_MAX_SAMPLES,
        storage_max_samples: int = STORAGE_MAX_SAMPLES,
    ) -> None:
        self.cpu = MetricHistory(max_samples=cpu_max_samples)
        self.memory = MetricHistory(max_samples=memory_max_samples)
        self.battery = MetricHistory(max_samples=battery_max_samples)
        self.storage = MetricHistory(max_samples=storage_max_samples)
        self.device_serial: str | None = None
        self.session_started_at: float | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin_session(self, device_serial: str | None, timestamp: float | None = None) -> None:
        """Start (or restart) the session for a device.

        Resets every window: history is per-session and per-device; a
        reconnect or a device switch must never inherit the previous
        device's data.
        """
        self.clear()
        self.device_serial = device_serial
        self.session_started_at = timestamp

    def clear(self) -> None:
        """Drop every sample (disconnect / new session)."""
        self.cpu.clear()
        self.memory.clear()
        self.battery.clear()
        self.storage.clear()
        self.device_serial = None
        self.session_started_at = None

    # ------------------------------------------------------------------
    # Recording (values are 0–100 percentages of the live snapshots)
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        cpu_used_percent: float | None,
        memory_used_percent: float | None,
        battery_level_percent: float | None,
        storage_used_percent: float | None,
        timestamp: float | None = None,
    ) -> None:
        """Record one sample per metric; None values are skipped."""
        self.cpu.add_sample(cpu_used_percent, timestamp)
        self.memory.add_sample(memory_used_percent, timestamp)
        self.battery.add_sample(battery_level_percent, timestamp)
        self.storage.add_sample(storage_used_percent, timestamp)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def metric(self, key: str) -> MetricHistory:
        """The history of one canonical metric key."""
        return {
            METRIC_CPU: self.cpu,
            METRIC_MEMORY: self.memory,
            METRIC_BATTERY: self.battery,
            METRIC_STORAGE: self.storage,
        }[key]

    def stats(self) -> SessionStats:
        """Deterministic statistics of every metric in the session."""
        return SessionStats(
            cpu=self.cpu.stats(),
            memory=self.memory.stats(),
            battery=self.battery.stats(),
            storage=self.storage.stats(),
        )

    @property
    def is_empty(self) -> bool:
        return all(history.is_empty for history in self._histories())

    def _histories(self) -> tuple[MetricHistory, ...]:
        return (self.cpu, self.memory, self.battery, self.storage)


__all__ = [
    "BATTERY_MAX_SAMPLES",
    "CPU_MAX_SAMPLES",
    "MEMORY_MAX_SAMPLES",
    "METRIC_BATTERY",
    "METRIC_CPU",
    "METRIC_MEMORY",
    "METRIC_STORAGE",
    "STORAGE_MAX_SAMPLES",
    "SessionHistory",
    "SessionStats",
]
