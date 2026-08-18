"""Unit tests for the live storage collector and its model.

Fixture values match the verified Vivo V2026 ``df -k /data`` output used
across the device-information tests. No device is required.
"""

from __future__ import annotations

from android_task_manager.storage.collector import StorageCollector
from android_task_manager.storage.models import StorageSnapshot

#: Verified Vivo V2026 ``df -k /data`` output (same numbers as the
#: device-information fixtures: 57% used of 121,934,848 KiB).
FIXTURE_DF = (
    "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
    "/dev/block/sda11 121934848 69120000 52814848 57% /data\n"
)


class _FakeRunner:
    """Serves a fixed ``df`` output and records commands issued."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):
        self.calls.append(list(args))
        return self.output


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_snapshot_used_percent() -> None:
    snapshot = StorageSnapshot(
        timestamp=1.0,
        mount="/data",
        total_kb=121934848,
        used_kb=69120000,
        available_kb=52814848,
    )
    assert snapshot.used_percent is not None
    assert snapshot.used_percent == 69120000 / 121934848 * 100


def test_snapshot_zero_total_yields_none_percent() -> None:
    snapshot = StorageSnapshot(
        timestamp=1.0, mount="/data", total_kb=0, used_kb=0, available_kb=0
    )
    assert snapshot.used_percent is None


def test_snapshot_zero_free_space_is_valid() -> None:
    snapshot = StorageSnapshot(
        timestamp=1.0,
        mount="/data",
        total_kb=1000,
        used_kb=1000,
        available_kb=0,
    )
    assert snapshot.used_percent == 100.0
    assert snapshot.available_kb == 0


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


def test_collector_builds_snapshot_from_verified_fixture() -> None:
    runner = _FakeRunner(FIXTURE_DF)
    snapshot = StorageCollector(runner).sample()
    assert isinstance(snapshot, StorageSnapshot)
    assert snapshot.mount == "/data"
    assert snapshot.total_kb == 121934848
    assert snapshot.used_kb == 69120000
    assert snapshot.available_kb == 52814848
    assert snapshot.timestamp >= 0.0


def test_collector_uses_existing_adb_facade() -> None:
    runner = _FakeRunner(FIXTURE_DF)
    StorageCollector(runner).sample()
    assert runner.calls == [["df", "-k", "/data"]]


def test_collector_header_only_output_returns_none() -> None:
    runner = _FakeRunner("Filesystem      1K-blocks     Used Available Use% Mounted on\n")
    assert StorageCollector(runner).sample() is None


def test_collector_empty_output_returns_none() -> None:
    assert StorageCollector(_FakeRunner("")).sample() is None


def test_collector_no_data_volume_returns_none() -> None:
    runner = _FakeRunner(
        "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
        "/dev/block/sda1 121934848 69120000 52814848 57% /sdcard\n"
    )
    assert StorageCollector(runner).sample() is None


def test_collector_malformed_numbers_returns_none() -> None:
    runner = _FakeRunner(
        "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
        "/dev/block/sda11 oops 69120000 52814848 57% /data\n"
    )
    assert StorageCollector(runner).sample() is None


def test_collector_unparseable_lines_returns_none() -> None:
    runner = _FakeRunner("df: /data: Permission denied\n")
    assert StorageCollector(runner).sample() is None


def test_collector_zero_used_is_not_fabricated() -> None:
    runner = _FakeRunner(
        "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
        "/dev/block/sda11 121934848 0 121934848 0% /data\n"
    )
    snapshot = StorageCollector(runner).sample()
    assert snapshot is not None
    assert snapshot.used_kb == 0
    assert snapshot.used_percent == 0.0