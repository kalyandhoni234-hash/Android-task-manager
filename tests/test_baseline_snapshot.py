"""Unit tests for the baseline snapshot builder (pure transformation).

No device required: the builder consumes already-collected, normalized
dataclasses (``ProcessInfo`` rows, installed package names plus the UID →
packages map, and a ``NetworkInvestigationSnapshot``), so every test is a
pure in-memory fixture.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from android_task_manager.baseline.models import (
    PackageIdentity,
    ProcessRef,
    SocketIdentity,
)
from android_task_manager.baseline.snapshot import build_snapshot
from android_task_manager.network_investigation.models import (
    NetworkInvestigationSnapshot,
    SocketInfo,
)
from android_task_manager.process.models import ProcessCategory, ProcessInfo

FIXED_CREATED_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
SERIAL = "R58M1234567"


def _process(pid: int, name: str, uid: int | None, category: ProcessCategory = ProcessCategory.USER) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        uid=uid,
        state="S",
        cpu_percent=0.5,
        memory_percent=0.25,
        category=category,
    )


def _socket(
    protocol: str = "tcp",
    address: str = "0.0.0.0",
    port: int = 8080,
    uid: int | None = 10200,
) -> SocketInfo:
    return SocketInfo(
        protocol=protocol,
        family="ipv4",
        local_address=address,
        local_port=port,
        state="0A",
        uid=uid,
    )


def _investigation(
    sockets: tuple[SocketInfo, ...],
    source_available: bool = True,
    uid_packages: dict[int, tuple[str, ...]] | None = None,
) -> NetworkInvestigationSnapshot:
    return NetworkInvestigationSnapshot(
        sockets=sockets,
        source_available=source_available,
        uid_packages=uid_packages or {},
    )


# ---------------------------------------------------------------------------
# Processes.
# ---------------------------------------------------------------------------


def test_processes_map_to_pidless_stable_refs() -> None:
    snapshot = build_snapshot(
        SERIAL,
        [_process(123, "com.example.app", 10200)],
        (),
        sockets=None,
        created_at=FIXED_CREATED_AT,
    )
    assert snapshot.processes == frozenset(
        {ProcessRef(uid=10200, process_name="com.example.app", classification=ProcessCategory.USER)}
    )


def test_pid_change_produces_identical_process_identity() -> None:
    """The identity on which the diff engine relies must be PID-free."""
    pid_one = build_snapshot(
        SERIAL, [_process(1001, "com.example.chrome", 10205)], (), sockets=None
    )
    pid_two = build_snapshot(
        SERIAL, [_process(2222, "com.example.chrome", 10205)], (), sockets=None
    )
    assert pid_one.processes == pid_two.processes
    assert not ProcessRef.__dataclass_fields__.keys() >= {"pid"}


def test_process_category_and_unknown_uid_are_kept_honest() -> None:
    snapshot = build_snapshot(
        SERIAL,
        [
            _process(1, "[kworker/0:1]", 0, ProcessCategory.KERNEL_THREAD),
            _process(2, "top-only-app", None, ProcessCategory.SYSTEM),
        ],
        (),
        sockets=None,
    )
    assert snapshot.processes == frozenset(
        {
            ProcessRef(uid=0, process_name="[kworker/0:1]", classification=ProcessCategory.KERNEL_THREAD),
            ProcessRef(uid=None, process_name="top-only-app", classification=ProcessCategory.SYSTEM),
        }
    )


def test_placeholder_pid_name_rows_are_skipped() -> None:
    """``<pid N>`` rows embed the PID: no stable identity, never diffed."""
    snapshot = build_snapshot(
        SERIAL,
        [_process(77, "<pid 77>", None, ProcessCategory.SYSTEM)],
        (),
        sockets=None,
    )
    assert snapshot.processes == frozenset()


def test_duplicate_processes_deduplicate() -> None:
    snapshot = build_snapshot(
        SERIAL,
        [_process(1, "com.example.app", 10200), _process(2, "com.example.app", 10200)],
        (),
        sockets=None,
    )
    assert len(snapshot.processes) == 1


# ---------------------------------------------------------------------------
# Packages.
# ---------------------------------------------------------------------------


def test_packages_without_uid_map_keep_uid_none() -> None:
    snapshot = build_snapshot(SERIAL, (), {"com.example.app", "org.example.lib"}, sockets=None)
    assert snapshot.packages == frozenset(
        {
            PackageIdentity(package_name="com.example.app", uid=None),
            PackageIdentity(package_name="org.example.lib", uid=None),
        }
    )


def test_uid_packages_map_is_inverted_into_package_uids() -> None:
    snapshot = build_snapshot(
        SERIAL,
        (),
        {"com.example.app", "com.example.other", "org.example.lib"},
        uid_packages={10200: ("com.example.app",), 10201: ("com.example.other", "org.example.lib")},
        sockets=None,
    )
    assert snapshot.packages == frozenset(
        {
            PackageIdentity(package_name="com.example.app", uid=10200),
            PackageIdentity(package_name="com.example.other", uid=10201),
            PackageIdentity(package_name="org.example.lib", uid=10201),
        }
    )


def test_package_mapped_by_multiple_uids_keeps_uid_none() -> None:
    """Choosing one UID would fabricate an attribution; None stays honest."""
    snapshot = build_snapshot(
        SERIAL,
        (),
        {"com.example.shared"},
        uid_packages={10200: ("com.example.shared",), 10201: ("com.example.shared",)},
        sockets=None,
    )
    assert snapshot.packages == frozenset({PackageIdentity(package_name="com.example.shared", uid=None)})


def test_no_uid_packages_and_empty_installed_list() -> None:
    snapshot = build_snapshot(SERIAL, (), (), sockets=None)
    assert snapshot.packages == frozenset()


# ---------------------------------------------------------------------------
# Sockets.
# ---------------------------------------------------------------------------


def test_sockets_map_preserves_protocol_address_port_uid() -> None:
    snapshot = build_snapshot(
        SERIAL,
        (),
        (),
        sockets=_investigation((_socket("tcp6", "::1", 5050, 1000),)),
    )
    assert snapshot.sockets == frozenset(
        {SocketIdentity(protocol="tcp6", local_address="::1", local_port=5050, uid=1000)}
    )


def test_socket_without_uid_attribution_keeps_uid_none() -> None:
    snapshot = build_snapshot(
        SERIAL,
        (),
        (),
        sockets=_investigation((_socket("udp", "0.0.0.0", 59393, None),)),
    )
    assert snapshot.sockets == frozenset({SocketIdentity(protocol="udp", local_address="0.0.0.0", local_port=59393, uid=None)})


def test_socket_rows_without_address_or_port_are_skipped() -> None:
    no_address = _socket("tcp", None, 8080)  # type: ignore[arg-type]
    no_port = _socket("udp", "0.0.0.0", None)  # type: ignore[arg-type]
    snapshot = build_snapshot(SERIAL, (), (), sockets=_investigation((no_address, no_port)))
    assert snapshot.sockets == frozenset()


def test_socket_with_zero_port_is_kept() -> None:
    """Port 0 is a real kernel value (UDP bind), never treated as junk."""
    snapshot = build_snapshot(
        SERIAL,
        (),
        (),
        sockets=_investigation((_socket("udp", "127.0.0.1", 0, 10203),)),
    )
    assert snapshot.sockets == frozenset({SocketIdentity(protocol="udp", local_address="127.0.0.1", local_port=0, uid=10203)})


# ---------------------------------------------------------------------------
# Verification flags and metadata.
# ---------------------------------------------------------------------------


def test_sockets_verified_defaults_to_source_available() -> None:
    refused = build_snapshot(SERIAL, (), (), sockets=_investigation((_socket(),), source_available=False))
    assert refused.sockets_verified is False
    ok = build_snapshot(SERIAL, (), (), sockets=_investigation((_socket(),), source_available=True))
    assert ok.sockets_verified is True


def test_no_sockets_input_forces_sockets_unverified() -> None:
    snapshot = build_snapshot(SERIAL, (), ())
    assert snapshot.sockets_verified is False


def test_sockets_verified_explicit_override() -> None:
    snapshot = build_snapshot(
        SERIAL,
        (),
        (),
        sockets=_investigation((_socket(),), source_available=False),
        sockets_verified=True,
    )
    assert snapshot.sockets_verified is True


def test_process_and_package_verified_flags_default_true_and_overridable() -> None:
    defaulted = build_snapshot(SERIAL, [_process(1, "a", 1)], {"x.pkg"}, sockets=None)
    assert defaulted.processes_verified is True
    assert defaulted.packages_verified is True
    explicit = build_snapshot(
        SERIAL,
        [_process(1, "a", 1)],
        {"x.pkg"},
        sockets=None,
        processes_verified=False,
        packages_verified=False,
    )
    assert explicit.processes_verified is False
    assert explicit.packages_verified is False


def test_device_serial_and_created_at_are_recorded() -> None:
    snapshot = build_snapshot(SERIAL, (), (), sockets=None, created_at=FIXED_CREATED_AT)
    assert snapshot.device_serial == SERIAL
    assert snapshot.created_at == FIXED_CREATED_AT


def test_created_at_defaults_to_aware_utc_now() -> None:
    snapshot = build_snapshot(SERIAL, (), (), sockets=None)
    assert isinstance(snapshot.created_at, datetime)
    assert snapshot.created_at.tzinfo is not None


def test_installed_packages_without_sockets_input() -> None:
    snapshot = build_snapshot(SERIAL, (), {"com.example.app"}, sockets=None)
    assert snapshot.packages == frozenset({PackageIdentity(package_name="com.example.app", uid=None)})
    assert snapshot.sockets_verified is False