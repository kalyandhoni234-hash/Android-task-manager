"""Unit tests for /proc/meminfo parsing, memory models and the memory collector.

Fixtures are based on the verified Vivo V2026 output. No device is required.
"""

from __future__ import annotations

import pytest

from android_task_manager.memory.collector import MemoryCollector
from android_task_manager.memory.models import MemorySnapshot
from android_task_manager.memory.parser import MemoryParseError, parse_meminfo
from android_task_manager.terminal.renderer import format_kib

# Verified Vivo V2026 /proc/meminfo (subset) fixture.
FIXTURE_MEMINFO = """MemTotal:        2865476 kB
MemFree:           37752 kB
MemAvailable:     478532 kB
Buffers:            7116 kB
Cached:           596568 kB
SwapCached:        28220 kB
SwapTotal:        1048572 kB
SwapFree:         959836 kB
Dirty:                24 kB
Writeback:              0 kB
"""


def test_parse_real_vivo_fixture() -> None:
    values = parse_meminfo(FIXTURE_MEMINFO)
    assert values == {
        "total_kb": 2865476,
        "free_kb": 37752,
        "available_kb": 478532,
        "buffers_kb": 7116,
        "cached_kb": 596568,
        "swap_cached_kb": 28220,
    }


def test_parse_required_fields_present() -> None:
    values = parse_meminfo(FIXTURE_MEMINFO)
    for key in (
        "total_kb",
        "free_kb",
        "available_kb",
        "buffers_kb",
        "cached_kb",
        "swap_cached_kb",
    ):
        assert key in values


def test_parse_fields_in_different_order() -> None:
    reordered = "\n".join(
        reversed([line for line in FIXTURE_MEMINFO.strip().splitlines()])
    ) + "\n"
    assert parse_meminfo(reordered) == parse_meminfo(FIXTURE_MEMINFO)


def test_parse_tolerates_additional_unknown_fields() -> None:
    extra = (
        FIXTURE_MEMINFO
        + "AnonPages:         12345 kB\n"
        + "HugePages_Total:       0\n"
        + "FictionalVendor: 99999 kB\n"
    )
    values = parse_meminfo(extra)
    assert values["total_kb"] == 2865476
    assert values["available_kb"] == 478532


def test_parse_malformed_required_field_raises() -> None:
    bad = FIXTURE_MEMINFO.replace("2865476", "notanumber")
    with pytest.raises(MemoryParseError):
        parse_meminfo(bad)


def test_parse_malformed_optional_field_ignored() -> None:
    # A malformed unknown field must not break parsing.
    bad_extra = FIXTURE_MEMINFO + "SomeUnknownField: oops kB\n"
    assert parse_meminfo(bad_extra)["total_kb"] == 2865476


def test_parse_missing_required_field_raises() -> None:
    without_available = FIXTURE_MEMINFO.replace("MemAvailable:     478532 kB\n", "")
    with pytest.raises(MemoryParseError):
        parse_meminfo(without_available)


def test_parse_field_without_value_raises() -> None:
    no_value = FIXTURE_MEMINFO.replace("MemTotal:        2865476 kB", "MemTotal:")
    with pytest.raises(MemoryParseError):
        parse_meminfo(no_value)


def test_parse_empty_input_raises() -> None:
    with pytest.raises(MemoryParseError):
        parse_meminfo("")


def test_kb_values_are_normalized_integers() -> None:
    values = parse_meminfo(FIXTURE_MEMINFO)
    assert all(isinstance(v, int) for v in values.values())


def test_snapshot_used_kb_is_total_minus_available() -> None:
    snap = MemorySnapshot(
        timestamp=0.0,
        total_kb=2865476,
        free_kb=37752,
        available_kb=478532,
        buffers_kb=7116,
        cached_kb=596568,
        swap_cached_kb=28220,
    )
    # used as total - available (NOT total - free), MemAvailable is primary.
    assert snap.used_kb == 2865476 - 478532


class _FakeRunner:
    """Serves a fixed /proc/meminfo blob and records commands issued."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        return self.output


def test_collector_reads_via_runner_and_builds_snapshot() -> None:
    runner = _FakeRunner(FIXTURE_MEMINFO)
    snapshot = MemoryCollector(runner).sample()
    assert isinstance(snapshot, MemorySnapshot)
    assert snapshot.total_kb == 2865476
    assert snapshot.available_kb == 478532
    assert snapshot.free_kb == 37752
    assert snapshot.buffers_kb == 7116
    assert snapshot.cached_kb == 596568
    assert snapshot.swap_cached_kb == 28220
    assert snapshot.timestamp >= 0.0
    assert runner.calls == [["cat", "/proc/meminfo"]]


def test_collector_reuses_existing_adb_facade() -> None:
    # The collector only depends on the shared CommandRunner (shell()).
    runner = _FakeRunner(FIXTURE_MEMINFO)
    MemoryCollector(runner).sample()
    assert runner.calls[0][0] == "cat"
    assert runner.calls[0][1] == "/proc/meminfo"


def test_collector_raises_on_malformed_output() -> None:
    runner = _FakeRunner("ThisIsNotMeminfo: abc\n")
    with pytest.raises(MemoryParseError):
        MemoryCollector(runner).sample()


def test_format_kib_binary_units() -> None:
    assert format_kib(2865476) == "2.73 GB"  # 2865476 / 1024^2 = 2.732...
    assert format_kib(478532) == "467 MB"    # 478532 / 1024 = 467.3...
    assert format_kib(37752) == "37 MB"
    assert format_kib(596568) == "583 MB"
    assert format_kib(7116) == "7 MB"
    assert format_kib(512) == "512 KB"