"""Unit tests for CPU delta calculation and collector behavior.

Tests never talk to a device; the collector is driven through a fake command
runner. Fixtures mirror the verified Vivo V2026 /proc/stat output.
"""

from __future__ import annotations

import pytest

from android_task_manager.adb.exceptions import ADBCommandError
from android_task_manager.cpu.calculation import calculate_delta, utilization_percent
from android_task_manager.cpu.collector import CPUCollector
from android_task_manager.cpu.models import CPUCounters

# Two /proc/stat snapshots. SNAP2 is SNAP1 with fixed increments applied to
# every CPU: user +100, nice +20, system +50, idle +500, iowait +5, irq +0,
# softirq +8. This makes each busy_delta 178 and total_delta 683,
# i.e. utilization = 178 / 683 * 100 (for the aggregate and every core).
SNAP1 = """cpu  7412737 2342824 5072560 9694054 136941 0 130749 0 0 0
cpu0 964099 248320 566456 7221915 98910 0 49620 0 0 0
cpu1 1014502 248553 521306 369970 3893 0 20794 0 0 0
cpu2 1151384 248911 526385 364085 4882 0 15010 0 0 0
cpu3 1262127 249976 543853 359919 4999 0 10144 0 0 0
cpu4 831524 354250 820306 336104 6071 0 8340 0 0 0
cpu5 775535 357218 734124 340794 6183 0 9635 0 0 0
cpu6 715721 320374 690181 348561 5982 0 8336 0 0 0
cpu7 697844 315219 669945 352702 6018 0 8868 0 0 0
"""

SNAP2 = """cpu  7412837 2342844 5072610 9694554 136946 0 130757 0 0 0
cpu0 964199 248340 566506 7222415 98915 0 49628 0 0 0
cpu1 1014602 248573 521356 370470 3898 0 20802 0 0 0
cpu2 1151484 248931 526435 364585 4887 0 15018 0 0 0
cpu3 1262227 249996 543903 360419 5004 0 10152 0 0 0
cpu4 831624 354270 820356 336604 6076 0 8348 0 0 0
cpu5 775635 357238 734174 341294 6188 0 9643 0 0 0
cpu6 715821 320394 690231 349061 5987 0 8344 0 0 0
cpu7 697944 315239 669995 353202 6023 0 8876 0 0 0
"""

DEFAULT_FREQ = {i: str(1200000) for i in range(8)}


def _counters(
    core_id,
    user,
    nice,
    system,
    idle,
    iowait,
    irq=0,
    softirq=0,
) -> CPUCounters:
    return CPUCounters(
        core_id=core_id,
        user=user,
        nice=nice,
        system=system,
        idle=idle,
        iowait=iowait,
        irq=irq,
        softirq=softirq,
    )


class FakeRunner:
    """Replays fixed /proc/stat snapshots and serves cpufreq nodes."""

    def __init__(self, snapshots, freq_map=None, freq_error_cores=()):
        self._snapshots = list(snapshots)
        freq = dict(DEFAULT_FREQ)
        freq.update(freq_map or {})
        self._freq_map = freq
        self._freq_error_cores = set(freq_error_cores)
        self._index = 0
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        if list(args) == ["cat", "/proc/stat"]:
            slot = min(self._index, len(self._snapshots) - 1)
            self._index += 1
            return self._snapshots[slot]
        path = args[1]
        for core_id, raw in self._freq_map.items():
            if f"/cpu{core_id}/cpufreq/scaling_cur_freq" in path:
                if core_id in self._freq_error_cores:
                    raise ADBCommandError(
                        f"shell cat {path}",
                        1,
                        stderr=f"cat: {path}: No such file or directory",
                    )
                return raw
        raise AssertionError(f"Unexpected command: {args}")


def test_calculate_delta_busy_and_total() -> None:
    prev = _counters(0, user=100, nice=0, system=50, idle=800, iowait=10, irq=5, softirq=5)
    curr = _counters(0, user=200, nice=0, system=100, idle=900, iowait=20, irq=10, softirq=10)
    delta = calculate_delta(prev, curr)
    assert delta.core_id == 0
    assert delta.busy == 160  # (user100 + sys50 + irq5 + softirq5)
    assert delta.total == 270  # busy + idle(100) + iowait(10)


def test_utilization_percent_basic() -> None:
    prev = _counters(0, user=100, nice=0, system=50, idle=800, iowait=10, irq=5, softirq=5)
    curr = _counters(0, user=200, nice=0, system=100, idle=900, iowait=20, irq=10, softirq=10)
    delta = calculate_delta(prev, curr)
    assert utilization_percent(delta) == pytest.approx(160 / 270 * 100, abs=1e-9)


def test_per_core_delta_uses_full_busy_equation() -> None:
    # user 0, nice 20, system 0, idle 700 -> busy_delta 20, total_delta 70
    prev = _counters(1, user=0, nice=10, system=0, idle=1000, iowait=0)
    curr = _counters(1, user=0, nice=30, system=0, idle=1300, iowait=0)
    delta = calculate_delta(prev, curr)
    assert delta.busy == 20
    assert delta.total == 320
    assert utilization_percent(delta) == pytest.approx(20 / 320 * 100, abs=1e-9)


def test_zero_delta_returns_zero() -> None:
    counts = _counters(0, user=100, nice=0, system=50, idle=800, iowait=10, irq=5, softirq=5)
    delta = calculate_delta(counts, counts)
    assert delta.busy == 0
    assert delta.total == 0
    assert utilization_percent(delta) == 0.0


def test_zero_or_negative_total_delta_returns_zero() -> None:
    prev = _counters(0, user=0, nice=0, system=0, idle=1000, iowait=0)
    curr = _counters(0, user=0, nice=0, system=0, idle=900, iowait=0)
    delta = calculate_delta(prev, curr)
    assert delta.total < 0
    assert utilization_percent(delta) == 0.0


def test_utilization_clamped_to_100_when_busy_exceeds_total() -> None:
    # idle drops between samples, so total < busy -> >100% -> clamped.
    prev = _counters(0, user=0, nice=0, system=0, idle=1000, iowait=0)
    curr = _counters(0, user=0, nice=0, system=500, idle=900, iowait=0)
    delta = calculate_delta(prev, curr)
    assert delta.total == 400
    assert utilization_percent(delta) == 100.0


def test_calculate_delta_mismatched_core_ids_raise() -> None:
    prev = _counters(0, user=1, nice=0, system=0, idle=1, iowait=0)
    curr = _counters(1, user=1, nice=0, system=0, idle=1, iowait=0)
    with pytest.raises(ValueError):
        calculate_delta(prev, curr)


def test_first_sample_reports_utilization_unavailable() -> None:
    runner = FakeRunner([SNAP1, SNAP2])
    collector = CPUCollector(runner)
    first = collector.sample()
    assert first.aggregate_utilization_percent is None
    assert all(core.utilization_percent is None for core in first.cores)
    assert len(first.cores) == 8
    assert all(core.frequency_available for core in first.cores)


def test_second_sample_reports_real_utilization() -> None:
    runner = FakeRunner([SNAP1, SNAP2])
    collector = CPUCollector(runner)
    collector.sample()  # establish baseline (N/A)
    second = collector.sample()
    expected = 178 / 683 * 100
    assert second.aggregate_utilization_percent == pytest.approx(expected, abs=1e-9)
    for core in second.cores:
        assert core.utilization_percent == pytest.approx(expected, abs=1e-9)


def test_collector_issues_stat_and_frequency_commands() -> None:
    runner = FakeRunner([SNAP1])
    CPUCollector(runner).sample()
    command_lists = runner.calls
    assert ["cat", "/proc/stat"] in command_lists
    for core_id in range(8):
        assert [f"cat", f"/sys/devices/system/cpu/cpu{core_id}/cpufreq/scaling_cur_freq"] in command_lists


def test_collector_parses_frequency_to_khz() -> None:
    runner = FakeRunner([SNAP1], freq_map={0: "1617000", 1: "644000"})
    snapshot = CPUCollector(runner).sample()
    by_id = {c.core_id: c for c in snapshot.cores}
    assert by_id[0].frequency_khz == 1617000
    assert by_id[1].frequency_khz == 644000


def test_unavailable_frequency_does_not_crash_collector() -> None:
    runner = FakeRunner([SNAP1], freq_error_cores={0})
    snapshot = CPUCollector(runner).sample()
    by_id = {c.core_id: c for c in snapshot.cores}
    assert by_id[0].frequency_available is False
    assert by_id[0].frequency_khz is None
    assert by_id[1].frequency_available is True
    assert snapshot.aggregate_utilization_percent is None


def test_bad_frequency_text_marks_core_unavailable() -> None:
    runner = FakeRunner([SNAP1], freq_map={0: "no data here"})
    snapshot = CPUCollector(runner).sample()
    by_id = {c.core_id: c for c in snapshot.cores}
    assert by_id[0].frequency_available is False


def test_frequency_error_does_not_abort_second_sample() -> None:
    runner = FakeRunner([SNAP1, SNAP2], freq_error_cores={7})
    collector = CPUCollector(runner)
    collector.sample()
    second = collector.sample()
    assert second.aggregate_utilization_percent is not None
    for core in second.cores:
        if core.core_id == 7:
            assert core.frequency_available is False
        else:
            assert core.frequency_available is True