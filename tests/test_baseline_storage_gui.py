"""Headless GUI tests for baseline persistence integration (D4).

Offscreen Qt platform; never touches a device or the real user-data
directory — stores are built over ``tmp_path`` and assigned to the
window. Covers: persist-on-save, auto-load on connect, session baseline
wins over disk, persistence-failure status, and hermetic no-store
behavior.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.baseline import BaselineSnapshot, BaselineStore, ProcessRef
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.process.models import ProcessCategory

_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
_SERIAL = "TEST123"


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _proc(name: str, uid: int) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=ProcessCategory.USER)


def _snapshot(serial: str = _SERIAL) -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=_AT,
        device_serial=serial,
        processes=frozenset({_proc("com.kept.app", 10002)}),
        packages=frozenset(),
        sockets=frozenset(),
    )


def _header(window: MainWindow) -> str:
    return window.security._baseline_label.text()


# ---------------------------------------------------------------------------
# Persist on save
# ---------------------------------------------------------------------------


def test_saved_baseline_is_persisted_to_store(qtapp, tmp_path):
    window = MainWindow()
    window.baseline_store = BaselineStore(tmp_path)
    window.on_baseline_saved(_snapshot())
    assert window.baseline_store.exists(_SERIAL)
    assert window.baseline_store.load(_SERIAL) == _snapshot()
    assert "(created)" in _header(window)
    window.close()


def test_save_persist_failure_is_surfaced(qtapp, tmp_path):
    window = MainWindow()
    store = BaselineStore(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    (tmp_path / "baseline-TEST123.json").mkdir()
    window.baseline_store = store
    window.on_baseline_saved(_snapshot())
    assert "could not be saved to disk" in window.security._status.text()
    window.close()


# ---------------------------------------------------------------------------
# Auto-load on connect
# ---------------------------------------------------------------------------


def test_auto_load_restores_stored_baseline(qtapp, tmp_path):
    window = MainWindow()
    window.baseline_store = BaselineStore(tmp_path)
    window.baseline_store.save(_snapshot())
    assert window._baseline is None
    window.on_serial_ready(_SERIAL)
    assert window._baseline == _snapshot()
    assert "(loaded)" in _header(window)
    assert window.security._check_btn.isEnabled()
    window.close()


def test_auto_load_skips_missing_baseline(qtapp, tmp_path):
    window = MainWindow()
    window.baseline_store = BaselineStore(tmp_path)
    window.on_serial_ready("NOPE")
    assert window._baseline is None
    assert "Baseline: Not set" in _header(window)
    window.close()


def test_auto_load_skips_corrupt_baseline(qtapp, tmp_path):
    window = MainWindow()
    store = BaselineStore(tmp_path)
    store.path_for(_SERIAL).write_text("{broken", encoding="utf-8")
    window.baseline_store = store
    window.on_serial_ready(_SERIAL)
    assert window._baseline is None
    window.close()


def test_session_baseline_wins_over_disk(qtapp, tmp_path):
    window = MainWindow()
    store = BaselineStore(tmp_path)
    store.save(_snapshot())
    window.baseline_store = store
    window.on_baseline_saved(_snapshot())
    assert "(created)" in _header(window)
    window.on_serial_ready(_SERIAL)
    assert "(created)" in _header(window)
    window.close()


def test_wrong_device_never_loads_into_window(qtapp, tmp_path):
    window = MainWindow()
    store = BaselineStore(tmp_path)
    store.save(_snapshot(serial="DEVICE-A"))
    window.baseline_store = store
    window.on_serial_ready("DEVICE-B")
    assert window._baseline is None
    window.close()


# ---------------------------------------------------------------------------
# Hermetic no-store behavior
# ---------------------------------------------------------------------------


def test_no_store_never_touches_disk(qtapp, tmp_path, monkeypatch):
    window = MainWindow()
    called = []
    monkeypatch.setattr(
        "android_task_manager.baseline.storage.BaselineStore.load",
        lambda self, serial: called.append(serial),
    )
    window.on_serial_ready(_SERIAL)
    assert called == []
    assert window._device_serial == _SERIAL
    assert window._baseline is None
    window.on_baseline_saved(_snapshot())
    assert "(created)" in _header(window)
    window.close()


def test_disconnect_clears_serial(qtapp):
    from android_task_manager.gui.monitor import ConnectionState

    window = MainWindow()
    window.on_serial_ready(_SERIAL)
    assert window._device_serial == _SERIAL
    window.update_connection(ConnectionState.DISCONNECTED, "no device")
    assert window._device_serial is None
    window.close()