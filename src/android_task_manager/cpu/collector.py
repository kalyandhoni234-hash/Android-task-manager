"""CPU collector: drives ADB reads and produces normalized CPU snapshots.

The collector never calls subprocess. It depends on the small ``CommandRunner``
interface defined in ``adb.connection`` (satisfied by ConnectionManager) so it
can be tested with a fake.
"""

from __future__ import annotations

import time
from typing import Sequence

from ..adb.connection import CommandRunner
from ..adb.exceptions import ADBError
from .calculation import calculate_delta, utilization_percent
from .models import CPUCore, CPUCounters, CPUSnapshot, ProcStat
from .parser import CPUParseError, parse_proc_stat, parse_scaling_frequency


class CPUCollector:
    """Samples /proc/stat and per-core CPU frequencies on the target device."""

    def __init__(self, runner: CommandRunner, timeout: float | None = None) -> None:
        self._runner = runner
        self._timeout = timeout
        self._previous: ProcStat | None = None

    def sample(self) -> CPUSnapshot:
        """Collect one CPU snapshot.

        The first call returns utilization ``None`` (no previous sample to
        compute a delta against). Subsequent calls return real percentages.
        """
        stat_text = self._runner.shell(["cat", "/proc/stat"], timeout=self._timeout)
        counters = parse_proc_stat(stat_text)

        frequencies = self._read_frequencies([c.core_id for c in counters.cores])  # type: ignore[misc]
        timestamp = time.monotonic()

        previous = self._previous
        self._previous = counters

        if previous is None:
            # No baseline yet: every core's utilization is "not available".
            cores = [
                CPUCore(
                    core_id=c.core_id,  # type: ignore[arg-type]
                    utilization_percent=None,
                    frequency_khz=frequencies.get(c.core_id),  # type: ignore[arg-type]
                    frequency_available=frequencies.get(c.core_id) is not None,
                )
                for c in counters.cores
            ]
            return CPUSnapshot(
                timestamp=timestamp,
                aggregate_utilization_percent=None,
                cores=cores,
                aggregate_counters=counters.aggregate,
                core_counters=counters.cores,
            )

        aggregate_pct = utilization_percent(
            calculate_delta(previous.aggregate, counters.aggregate)
        )

        previous_by_core = {c.core_id: c for c in previous.cores}  # type: ignore[misc]
        cores: list[CPUCore] = []
        for current in counters.cores:
            prior = previous_by_core.get(current.core_id)  # type: ignore[arg-type]
            pct: float | None = None
            if prior is not None:
                pct = utilization_percent(calculate_delta(prior, current))
            freq = frequencies.get(current.core_id)  # type: ignore[arg-type]
            cores.append(
                CPUCore(
                    core_id=current.core_id,  # type: ignore[arg-type]
                    utilization_percent=pct,
                    frequency_khz=freq,
                    frequency_available=freq is not None,
                )
            )

        return CPUSnapshot(
            timestamp=timestamp,
            aggregate_utilization_percent=aggregate_pct,
            cores=cores,
            aggregate_counters=counters.aggregate,
            core_counters=counters.cores,
        )

    def _read_frequencies(self, core_ids: Sequence[int]) -> dict[int, int | None]:
        """Read each core's current cpufreq in kHz.

        A missing/unreadable node marks that core's frequency as unavailable
        rather than aborting the whole sample.
        """
        frequencies: dict[int, int | None] = {}
        for core_id in core_ids:
            path = f"/sys/devices/system/cpu/cpu{core_id}/cpufreq/scaling_cur_freq"
            try:
                text = self._runner.shell(["cat", path], timeout=self._timeout)
                frequencies[core_id] = parse_scaling_frequency(text)
            except (ADBError, CPUParseError):
                # Unavailable frequency node — do not crash the monitor.
                frequencies[core_id] = None
        return frequencies