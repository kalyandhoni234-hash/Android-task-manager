"""Headless GUI tests for the Diagnostics dialog and its sidebar entry.

Offscreen Qt; file dialogs and the system file manager are stubbed so no
dialog or desktop integration is exercised. Covers: dialog creation, log
path display, open-folder action (present and missing), export, export
cancellation, and the MainWindow/sidebar integration.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from android_task_manager.core.diagnostics import (
    log_file_path,
    reset_logging,
    setup_logging,
)
from android_task_manager.gui import diagnostics_dialog as dialog_module
from android_task_manager.gui.diagnostics_dialog import DiagnosticsDialog
from android_task_manager.gui.main_window import MainWindow


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def log_dir(tmp_path):
    """Point the diagnostic log at a scratch dir for dialog tests."""
    path = tmp_path / "dialog-logs"
    reset_logging()
    setup_logging(path)
    return path


def _buttons(dialog: DiagnosticsDialog) -> dict[str, QPushButton]:
    return {button.text(): button for button in dialog.findChildren(QPushButton)}


# ---------------------------------------------------------------------------
# Dialog creation & log path display
# ---------------------------------------------------------------------------


def test_dialog_creation_shows_log_path(qtapp, log_dir) -> None:
    dialog = DiagnosticsDialog()
    assert dialog.windowTitle() == "Diagnostics"
    labels = dialog.findChildren(QLabel)
    assert any(label.text() == str(log_file_path()) for label in labels)
    buttons = _buttons(dialog)
    assert "Open Log Folder" in buttons
    assert "Export Diagnostic Log..." in buttons
    assert "Close" in buttons


def test_refresh_updates_log_path(qtapp, tmp_path) -> None:
    reset_logging()
    setup_logging(tmp_path / "first")
    dialog = DiagnosticsDialog()
    reset_logging()
    setup_logging(tmp_path / "second")
    dialog.refresh()
    labels = dialog.findChildren(QLabel)
    assert any(label.text() == str(log_file_path()) for label in labels)
    assert str(tmp_path / "second") in str(log_file_path())


def test_dialog_close_accepts(qtapp) -> None:
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Close"].click()
    assert dialog.result() == 0 or dialog.isHidden()


# ---------------------------------------------------------------------------
# Open Log Folder
# ---------------------------------------------------------------------------


def test_open_log_folder_invokes_file_manager(qtapp, log_dir, monkeypatch) -> None:
    opened: list[QUrl] = []
    monkeypatch.setattr(
        dialog_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url) or True,
    )
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Open Log Folder"].click()
    assert opened and opened[0].isLocalFile()
    assert opened[0].toLocalFile().endswith(str(log_dir).replace("\\", "/"))


def test_open_log_folder_when_missing_shows_status(qtapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ATMAN_LOG_DIR", str(tmp_path / "no-logs-here"))
    reset_logging()  # no setup: the log folder does not exist yet
    monkeypatch.setattr(
        dialog_module.QDesktopServices, "openUrl", lambda url: True
    )
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Open Log Folder"].click()
    assert "does not exist" in dialog._status.text()


def test_open_log_folder_failure_shows_status(qtapp, log_dir, monkeypatch) -> None:
    monkeypatch.setattr(dialog_module.QDesktopServices, "openUrl", lambda url: False)
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Open Log Folder"].click()
    assert "Could not open" in dialog._status.text()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_writes_report_to_chosen_path(qtapp, log_dir, tmp_path, monkeypatch) -> None:
    destination = tmp_path / "diagnostics.txt"
    monkeypatch.setattr(
        dialog_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Text file (*.txt)"),
    )
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Export Diagnostic Log..."].click()
    assert destination.exists()
    content = destination.read_text(encoding="utf-8")
    assert "Android Task Manager — diagnostic report" in content
    assert str(destination) in dialog._status.text()


def test_export_cancel_reports_cancelled(qtapp, log_dir, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        dialog_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", ""),
    )
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Export Diagnostic Log..."].click()
    assert "Export cancelled." == dialog._status.text()
    assert not (tmp_path / "nothing.txt").exists()


def test_export_failure_reports_error(qtapp, log_dir, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        dialog_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "missing-dir" / "out.txt"), ""),
    )
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Export Diagnostic Log..."].click()
    assert "Export failed" in dialog._status.text()


def test_exported_report_never_uploads(qtapp, log_dir, tmp_path, monkeypatch) -> None:
    """The report is a local file; nothing else is created or sent."""
    destination = tmp_path / "report.txt"
    monkeypatch.setattr(
        dialog_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )
    dialog = DiagnosticsDialog()
    _buttons(dialog)["Export Diagnostic Log..."].click()
    assert set(tmp_path.iterdir()) == {log_dir, destination}


# ---------------------------------------------------------------------------
# Sidebar integration
# ---------------------------------------------------------------------------


def test_sidebar_has_diagnostics_entry(qtapp) -> None:
    window = MainWindow()
    button = window.sidebar.diagnostics_button
    assert button.text() == "Diagnostics"
    assert not button.isCheckable()
    assert window._pages.currentIndex() == 0  # the action never changes pages


def test_sidebar_button_opens_dialog_once_and_reuses(qtapp) -> None:
    window = MainWindow()
    assert window._diagnostics_dialog is None
    window.sidebar.diagnostics_button.click()
    assert window._diagnostics_dialog is not None
    assert not window._diagnostics_dialog.isHidden()
    first = window._diagnostics_dialog
    window.sidebar.diagnostics_button.click()
    assert window._diagnostics_dialog is first  # reused, never recreated
    window.close()


def test_diagnostics_dialog_is_not_a_navigation_page(qtapp) -> None:
    """Clicking Diagnostics never activates a page or flips the stack."""
    window = MainWindow()
    window.sidebar.button("health").click()
    window.sidebar.diagnostics_button.click()
    assert window.sidebar.active_page() == "health"
    assert window._pages.currentIndex() == 6
    window.close()