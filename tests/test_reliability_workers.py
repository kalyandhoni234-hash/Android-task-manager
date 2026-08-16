"""Worker error observability tests.

Every worker must follow the same contract: a typed failure is reported
through the failure signal, an *unexpected* exception is reported through
the failure signal AND written (with its traceback) to the diagnostic log —
never crashing the GUI. Workers run synchronously here; the diagnostic log
is configured into a temporary directory.
"""

from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.action import ActionErrorKind, ActionResult
from android_task_manager.adb.exceptions import ADBNoDeviceError
from android_task_manager.core.diagnostics import (
    log_file_path,
    reset_logging,
    setup_logging,
)
from android_task_manager.gui.action_worker import ActionWorker
from android_task_manager.gui.baseline_worker import BaselineWorker
from android_task_manager.gui.incident_worker import IncidentWorker
from android_task_manager.gui.inspector_worker import ProcessInspectionWorker
from android_task_manager.gui.permission_worker import PermissionWorker
from android_task_manager.gui.update_worker import UpdateWorker


class _FakeConnection:
    """CommandRunner stand-in that raises a configured error from shell()."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error

    def verify_available(self) -> None:
        pass

    def require_device(self) -> str:
        return "FAKE123"

    def shell(self, args, timeout=None) -> str:
        if self.error is not None:
            raise self.error
        return ""

    def list_devices(self):
        return []


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def log_dir(tmp_path):
    """Point the diagnostic log at a scratch dir and return its path."""
    path = tmp_path / "worker-logs"
    reset_logging()
    setup_logging(path)
    return path


def _flush_log() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def _log_text(path) -> str:
    _flush_log()
    return log_file_path().read_text(encoding="utf-8")


def test_baseline_save_typed_failure_is_reported(log_dir) -> None:
    worker = BaselineWorker(connection=_FakeConnection(ADBNoDeviceError("none")))
    failed: list[str] = []
    worker.baseline_failed.connect(failed.append)
    worker.request_save_baseline()
    assert failed and "none" in failed[0]
    assert not worker.is_busy()


def test_baseline_save_unexpected_failure_logs_traceback(log_dir) -> None:
    worker = BaselineWorker(connection=_FakeConnection(RuntimeError("collector bug")))
    failed: list[str] = []
    worker.baseline_failed.connect(failed.append)
    worker.request_save_baseline()
    assert failed and "unexpectedly" in failed[0]
    text = _log_text(log_dir)
    assert "baseline raised unexpectedly during save" in text
    assert "Traceback (most recent call last)" in text
    assert "RuntimeError" in text


def test_drift_check_unexpected_failure_logs_traceback(log_dir) -> None:
    worker = BaselineWorker(connection=_FakeConnection(RuntimeError("diff bug")))
    failed: list[str] = []
    worker.drift_failed.connect(failed.append)
    worker.request_drift_check(object())
    assert failed and "unexpectedly" in failed[0]
    text = _log_text(log_dir)
    assert "baseline raised unexpectedly during check" in text


def test_action_unexpected_failure_is_typed_and_logged(log_dir) -> None:
    worker = ActionWorker(connection=_FakeConnection(RuntimeError("service bug")))
    results: list[ActionResult] = []
    worker.action_completed.connect(results.append)
    worker.request_action("open_app", "com.example.app")
    assert len(results) == 1
    assert results[0].success is False
    assert results[0].error_kind is ActionErrorKind.UNKNOWN
    assert "unexpectedly" in results[0].message
    text = _log_text(log_dir)
    assert "action raised unexpectedly during run" in text
    assert "Traceback" in text


def test_permission_audit_unexpected_failure_is_reported_and_logged(log_dir) -> None:
    worker = PermissionWorker(connection=_FakeConnection(RuntimeError("audit bug")))
    failed: list[tuple[str, str]] = []
    worker.audit_failed.connect(lambda pkg, msg: failed.append((pkg, msg)))
    worker.request_audit("com.example.app")
    assert failed and failed[0][0] == "com.example.app"
    assert "unexpectedly" in failed[0][1]
    text = _log_text(log_dir)
    assert "permissions raised unexpectedly during audit" in text


def test_inspection_unexpected_failure_is_reported_and_logged(log_dir) -> None:
    worker = ProcessInspectionWorker(connection=_FakeConnection(RuntimeError("inspector bug")))
    failed: list[tuple[int, str]] = []
    worker.inspection_failed.connect(lambda pid, msg: failed.append((pid, msg)))
    worker.request_inspect(123)
    assert failed and failed[0][0] == 123
    text = _log_text(log_dir)
    assert "inspection raised unexpectedly during sample" in text


def test_update_check_unexpected_failure_is_silent_and_logged(log_dir, monkeypatch) -> None:
    worker = UpdateWorker(current_version="0.4.0")
    completed: list = []

    def fake_check(version: str):
        raise RuntimeError("network bug")

    monkeypatch.setattr(
        "android_task_manager.gui.update_worker.check_for_update", fake_check
    )
    worker.check_completed.connect(completed.append)
    worker.request_check()

    assert completed and completed[0].error == "The update check failed unexpectedly."
    text = _log_text(log_dir)
    assert "updates raised unexpectedly during check" in text


def test_incident_export_unexpected_failure_is_reported_and_logged(log_dir) -> None:
    worker = IncidentWorker()
    completed: list[tuple[bool, str]] = []
    worker.export_completed.connect(lambda ok, msg: completed.append((ok, msg)))
    worker.request_export("json", str(log_dir / "out.json"), object())
    assert completed and completed[0][0] is False
    text = _log_text(log_dir)
    assert "incident raised unexpectedly during export" in text
    assert "Traceback" in text


def test_workers_report_typed_adb_failures_without_tracebacks(log_dir) -> None:
    """Expected ADB failures surface as clean messages, not tracebacks."""
    worker = PermissionWorker(connection=_FakeConnection(ADBNoDeviceError("none")))
    failed: list[tuple[str, str]] = []
    worker.audit_failed.connect(lambda pkg, msg: failed.append((pkg, msg)))
    worker.request_audit("com.example.app")
    assert failed and "none" in failed[0][1]
    text = _log_text(log_dir)
    assert "Traceback" not in text


def test_gui_survives_unexpected_worker_failures(qtapp, log_dir, monkeypatch) -> None:
    """Drive every worker through its unexpected-failure path in one run."""

    def fake_check(version: str):
        raise RuntimeError("network bug")

    monkeypatch.setattr(
        "android_task_manager.gui.update_worker.check_for_update", fake_check
    )
    workers = [
        BaselineWorker(connection=_FakeConnection(RuntimeError("x"))),
        ActionWorker(connection=_FakeConnection(RuntimeError("x"))),
        PermissionWorker(connection=_FakeConnection(RuntimeError("x"))),
        ProcessInspectionWorker(connection=_FakeConnection(RuntimeError("x"))),
        IncidentWorker(),
        UpdateWorker(current_version="0.4.0"),
    ]
    for worker in workers:
        if isinstance(worker, BaselineWorker):
            worker.request_save_baseline()
        elif isinstance(worker, ActionWorker):
            worker.request_action("open_app", "com.example.app")
        elif isinstance(worker, PermissionWorker):
            worker.request_audit("com.example.app")
        elif isinstance(worker, ProcessInspectionWorker):
            worker.request_inspect(1)
        elif isinstance(worker, IncidentWorker):
            worker.request_export("json", str(log_dir / "x.json"), object())
        else:
            worker.request_check()
    # The error-trapping never blocked; the log captured the tracebacks.
    text = _log_text(log_dir)
    assert text.count("raised unexpectedly") >= 5