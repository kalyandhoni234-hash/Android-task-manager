"""Core tests for persistent baseline storage (D4).

Pure storage tests — no GUI, no device, no ADB, and never the real user
data directory: every store is built over ``tmp_path``. Verifies the
D4 requirements: save/load round-trip, lifecycle persistence, missing /
corrupt / invalid / wrong-schema / wrong-device handling, atomic
replacement, permission failures, privacy, empty baselines, and that a
stored baseline still feeds the existing diff engine.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from android_task_manager.baseline import (
    BaselineSnapshot,
    BaselineStore,
    ProcessRef,
    diff_snapshot,
    sanitize_identifier,
    user_data_dir,
)
from android_task_manager.process.models import ProcessCategory

_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def _proc(name: str, uid: int) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=ProcessCategory.USER)


def _snapshot(serial: str = "TEST123") -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=_AT,
        device_serial=serial,
        processes=frozenset({_proc("com.kept.app", 10002)}),
        packages=frozenset(),
        sockets=frozenset(),
    )


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------


def test_save_then_load_round_trips_exactly(tmp_path):
    store = BaselineStore(tmp_path)
    snapshot = _snapshot()
    written = store.save(snapshot)
    assert written == store.path_for("TEST123")
    loaded = store.load("TEST123")
    assert loaded == snapshot
    assert loaded.device_serial == "TEST123"
    assert loaded.processes == snapshot.processes
    assert loaded.created_at == _AT


def test_lifecycle_persistence_across_store_instances(tmp_path):
    first = BaselineStore(tmp_path)
    first.save(_snapshot())
    second = BaselineStore(tmp_path)
    assert second.exists("TEST123")
    assert second.load("TEST123") == _snapshot()


def test_empty_baseline_round_trips(tmp_path):
    store = BaselineStore(tmp_path)
    empty = BaselineSnapshot(
        created_at=_AT,
        device_serial="EMPTY1",
        processes=frozenset(),
        packages=frozenset(),
        sockets=frozenset(),
    )
    store.save(empty)
    assert store.load("EMPTY1") == empty


# ---------------------------------------------------------------------------
# Missing / corrupt / invalid
# ---------------------------------------------------------------------------


def test_missing_file_loads_none(tmp_path):
    store = BaselineStore(tmp_path)
    assert store.load("NOSUCH") is None
    assert not store.exists("NOSUCH")


def test_corrupt_json_loads_none(tmp_path):
    store = BaselineStore(tmp_path)
    store.path_for("TEST123").write_text("{not json!!", encoding="utf-8")
    assert store.load("TEST123") is None
    assert store.exists("TEST123")


def test_invalid_json_types_load_none(tmp_path):
    store = BaselineStore(tmp_path)
    store.path_for("TEST123").write_text("[1, 2, 3]", encoding="utf-8")
    assert store.load("TEST123") is None


def test_unsupported_schema_loads_none(tmp_path):
    store = BaselineStore(tmp_path)
    envelope = {
        "schema_version": 999,
        "kind": "baseline",
        "device_serial": "TEST123",
        "created_at": _AT.isoformat(),
        "baseline": {},
    }
    store.path_for("TEST123").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    assert store.load("TEST123") is None


def test_wrong_kind_loads_none(tmp_path):
    store = BaselineStore(tmp_path)
    envelope = {
        "schema_version": 1,
        "kind": "something-else",
        "device_serial": "TEST123",
        "created_at": _AT.isoformat(),
        "baseline": {},
    }
    store.path_for("TEST123").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    assert store.load("TEST123") is None


def test_invalid_baseline_body_loads_none(tmp_path):
    store = BaselineStore(tmp_path)
    envelope = {
        "schema_version": 1,
        "kind": "baseline",
        "device_serial": "TEST123",
        "created_at": _AT.isoformat(),
        "baseline": {"processes": "not-a-list"},
    }
    store.path_for("TEST123").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    assert store.load("TEST123") is None


# ---------------------------------------------------------------------------
# Device association
# ---------------------------------------------------------------------------


def test_wrong_device_never_loads(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_snapshot(serial="DEVICE-A"))
    assert store.load("DEVICE-B") is None


def test_matching_device_loads_even_when_file_name_collides(tmp_path):
    # A hostile serial maps to a distinct sanitized filename, so two
    # devices can never share a store file.
    store = BaselineStore(tmp_path)
    a = _snapshot(serial="DEV/ICE;A")
    store.save(a)
    assert store.load("DEV/ICE;A") == a
    assert store.path_for("DEV/ICE;A") != store.path_for("DEVICE-A")


def test_envelope_device_serial_mismatch_loads_none(tmp_path):
    store = BaselineStore(tmp_path)
    envelope = {
        "schema_version": 1,
        "kind": "baseline",
        "device_serial": "OTHER",
        "created_at": _AT.isoformat(),
        "baseline": {},
    }
    store.path_for("TEST123").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    assert store.load("TEST123") is None


# ---------------------------------------------------------------------------
# Failure modes (permission / write)
# ---------------------------------------------------------------------------


def test_save_failure_raises_oserror(tmp_path):
    store = BaselineStore(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    blocker = tmp_path / "baseline-TEST123.json"
    blocker.mkdir()  # a directory where the file should go
    with pytest.raises(OSError):
        store.save(_snapshot())


def test_load_permission_error_returns_none(tmp_path, monkeypatch):
    store = BaselineStore(tmp_path)
    store.save(_snapshot())
    import builtins

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(builtins, "open", denied)
    assert store.load("TEST123") is None


def test_atomic_replace_leaves_no_temp_files(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_snapshot())
    store.save(_snapshot())  # replace over the existing file
    files = [p.name for p in tmp_path.iterdir()]
    assert files == ["baseline-TEST123.json"]
    assert store.load("TEST123") == _snapshot()


def test_save_creates_directory_recursively(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    store = BaselineStore(deep)
    store.save(_snapshot())
    assert store.load("TEST123") == _snapshot()


# ---------------------------------------------------------------------------
# Privacy / scope
# ---------------------------------------------------------------------------


def test_store_writes_only_its_envelope(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_snapshot())
    raw = store.path_for("TEST123").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert set(parsed) == {"schema_version", "kind", "device_serial", "created_at", "baseline"}
    assert parsed["kind"] == "baseline"
    assert parsed["device_serial"] == "TEST123"


def test_sanitize_identifier_is_filesystem_safe():
    assert sanitize_identifier("R58M29ABCDE") == "R58M29ABCDE"
    assert ".." not in sanitize_identifier("../..")
    assert "/" not in sanitize_identifier("a/b;c:d")
    assert len(sanitize_identifier("x" * 200)) <= 40


def test_user_data_dir_never_touches_disk(tmp_path, monkeypatch):
    # user_data_dir is a pure path computation; constructing a store over
    # it must not create anything until save() is called.
    import android_task_manager.baseline.storage as storage

    monkeypatch.setattr(storage, "sys", type("S", (), {"platform": "win32"})())
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = user_data_dir("TestApp")
    assert path == tmp_path / "local" / "TestApp"
    assert not path.exists()


# ---------------------------------------------------------------------------
# Existing comparison still works
# ---------------------------------------------------------------------------


def test_stored_baseline_feeds_drift_comparison(tmp_path):
    store = BaselineStore(tmp_path)
    store.save(_snapshot())
    baseline = store.load("TEST123")
    assert baseline is not None
    current = BaselineSnapshot(
        created_at=_AT,
        device_serial="TEST123",
        processes=frozenset(
            {
                _proc("com.kept.app", 10002),
                _proc("com.new.app", 10003),
            }
        ),
        packages=frozenset(),
        sockets=frozenset(),
    )
    report = diff_snapshot(baseline, current)
    assert [e.entity for e in report.events] == ["com.new.app"]