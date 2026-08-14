"""Unit tests for /proc/stat and cpufreq parsing.

Fixtures are based on the verified Vivo V2026 output. No device is required.
"""

from __future__ import annotations

import pytest

from android_task_manager.cpu.models import CPUCounters
from android_task_manager.cpu.parser import (
    CPUParseError,
    parse_proc_stat,
    parse_scaling_frequency,
)

# Verified Vivo V2026 /proc/stat fixture.
FIXTURE_STAT = """cpu  7412737 2342824 5072560 9694054 136941 0 130749 0 0 0
cpu0 964099 248320 566456 7221915 98910 0 49620 0 0 0
cpu1 1014502 248553 521306 369970 3893 0 20794 0 0 0
cpu2 1151384 248911 526385 364085 4882 0 15010 0 0 0
cpu3 1262127 249976 543853 359919 4999 0 10144 0 0 0
cpu4 831524 354250 820306 336104 6071 0 8340 0 0 0
cpu5 775535 357218 734124 340794 6183 0 9635 0 0 0
cpu6 715721 320374 690181 348561 5982 0 8336 0 0 0
cpu7 697844 315219 669945 352702 6018 0 8868 0 0 0
intr 12345678 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
ctxt 987654321
btime 1700000000
processes 12345
procs_running 6
procs_blocked 0
softirq 884422 2 4 123 5 6 7 8 9 10
"""


def test_parse_aggregate_line() -> None:
    parsed = parse_proc_stat(FIXTURE_STAT)
    agg = parsed.aggregate
    assert agg.core_id is None
    assert agg.user == 7412737
    assert agg.nice == 2342824
    assert agg.system == 5072560
    assert agg.idle == 9694054
    assert agg.iowait == 136941
    assert agg.irq == 0
    assert agg.softirq == 130749


def test_parse_per_core_lines() -> None:
    parsed = parse_proc_stat(FIXTURE_STAT)
    cpu0 = parsed.cores[0]
    assert cpu0.core_id == 0
    assert cpu0.user == 964099
    assert cpu0.nice == 248320
    assert cpu0.system == 566456
    assert cpu0.idle == 7221915
    assert cpu0.iowait == 98910
    assert cpu0.irq == 0
    assert cpu0.softirq == 49620


def test_discovers_all_eight_cores_dynamically() -> None:
    parsed = parse_proc_stat(FIXTURE_STAT)
    assert [c.core_id for c in parsed.cores] == [0, 1, 2, 3, 4, 5, 6, 7]


def test_discovers_arbitrary_core_count() -> None:
    text = (
        "cpu  1000 0 0 2000 0 0 0 0 0 0\n"
        "cpu0 100 0 0 500 0 0 0 0 0 0\n"
        "cpu1 200 0 0 400 0 0 0 0 0 0\n"
    )
    parsed = parse_proc_stat(text)
    assert [c.core_id for c in parsed.cores] == [0, 1]


def test_ignores_unrelated_lines() -> None:
    parsed = parse_proc_stat(FIXTURE_STAT)
    assert len(parsed.cores) == 8
    assert parsed.aggregate.core_id is None


def test_tolerates_additional_fields_after_std_fields() -> None:
    text = (
        "cpu  1 2 3 4 5 6 7 8 9 10 11 12\n"
        "cpu0 10 10 10 10 10 10 10 99 88 77 66 55\n"
    )
    parsed = parse_proc_stat(text)
    assert parsed.aggregate.softirq == 7
    assert parsed.cores[0].softirq == 10


def test_malformed_short_cpu_line_raises() -> None:
    with pytest.raises(CPUParseError):
        parse_proc_stat("cpu  1 2 3\n")


def test_malformed_non_integer_field_raises() -> None:
    with pytest.raises(CPUParseError):
        parse_proc_stat("cpu0 abc 1 2 3 4 6 7\n")


def test_malformed_non_numeric_core_suffix_raises() -> None:
    with pytest.raises(CPUParseError):
        parse_proc_stat("cpuX 1 2 3 4 5 6 7 8 9\n")


def test_missing_aggregate_line_raises() -> None:
    with pytest.raises(CPUParseError):
        parse_proc_stat("cpu0 1 2 3 4 5 6 7 0 0 0\n")


def test_parse_frequency_returns_khz() -> None:
    assert parse_scaling_frequency("1617000\n") == 1617000
    assert parse_scaling_frequency("  644000  \n") == 644000


def test_parse_frequency_malformed_raises() -> None:
    with pytest.raises(CPUParseError):
        parse_scaling_frequency("not a number\n")
    with pytest.raises(CPUParseError):
        parse_scaling_frequency("1617000 999\n")
    with pytest.raises(CPUParseError):
        parse_scaling_frequency("-1\n")
    with pytest.raises(CPUParseError):
        parse_scaling_frequency("")


def test_counter_fixture_types() -> None:
    parsed = parse_proc_stat(FIXTURE_STAT)
    assert isinstance(parsed.cores[0], CPUCounters)