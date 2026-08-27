"""Device-derived strings must render as literal plain text (Priority #5).

Offscreen, deterministic Qt tests over the REAL production paths:

* destructive-action confirmations (`_confirm_force_stop`,
  `_confirm_apps_action`) and dynamic informationals build instance-based
  QMessageBox objects with ``Qt.TextFormat.PlainText`` — hostile markup in a
  device/app-derived name can never be interpreted as rich text, and the
  exact wording/UX is preserved;
* setup-panel error messages echo raw ADB/host detail only as plain text;
* the process inspector renders device-controlled process names and command
  lines literally.

Dialogs are never shown: builder functions are asserted directly, and the
Yes/Cancel mapping is verified with a scripted ``exec`` subclass injected via
the production builder seam.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from android_task_manager.action.models import ActionResult
from android_task_manager.gui import main_window as mw
from android_task_manager.gui.setup_panel import SetupPanel
from android_task_manager.gui.widgets.process_inspector_widget import (
    ProcessInspectorWidget,
)
from android_task_manager.process.inspector_models import ProcessInspectionSnapshot

HOSTILE = '<font color="red"><b>DEVICE</b></font>'


@pytest.fixture(scope="module")
def qtapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _ScriptedBox(QMessageBox):
    """Real QMessageBox whose exec() is answered programmatically."""

    answer = QMessageBox.StandardButton.Yes
    instances: list["QMessageBox"] = []

    def exec(self) -> QMessageBox.StandardButton:  # type: ignore[override]
        _ScriptedBox.instances.append(self)
        return self.answer


# --------------------------------------------------------------------------
# 1-2-4. Confirmation dialog configuration + answer mapping
# --------------------------------------------------------------------------

def test_confirmation_builder_renders_hostile_markup_literally(qtapp):
    box = mw._build_confirmation(None, "Force Stop Application?", HOSTILE)

    assert box.textFormat() == Qt.TextFormat.PlainText
    assert box.text() == HOSTILE  # markup preserved literally, never styled
    assert box.windowTitle() == "Force Stop Application?"
    assert box.standardButtons() == (
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
    )
    assert box.defaultButton() is not None
    assert box.defaultButton().text().lower() == "cancel"


def test_confirmation_yes_maps_to_true_cancel_maps_to_false(qtapp, monkeypatch):
    captured_kwargs: list[tuple] = []

    def fake_builder(parent, title, text):
        captured_kwargs.append((parent, title, text))
        box = _ScriptedBox()
        box.setWindowTitle(title)
        box.setText(text)
        return box

    monkeypatch.setattr(mw, "_build_confirmation", fake_builder)

    _ScriptedBox.answer = QMessageBox.StandardButton.Yes
    assert mw._ask_confirmation(None, "T", "WhatsApp") is True
    _ScriptedBox.answer = QMessageBox.StandardButton.Cancel
    assert mw._ask_confirmation(None, "T", "WhatsApp") is False

    parent_arg, title_arg, text_arg = captured_kwargs[0]
    assert title_arg == "T" and text_arg == "WhatsApp" and parent_arg is None


def test_force_stop_prompt_keeps_wording_and_cancel_is_safe(qtapp, monkeypatch):
    window = SimpleNamespace(
        processes=SimpleNamespace(inspector=SimpleNamespace(display_name=lambda: HOSTILE))
    )
    captured: list[QMessageBox] = []

    def fake_builder(parent, title, text):
        box = _ScriptedBox()
        box.setWindowTitle(title)
        box.setText(text)
        captured.append(box)
        return box

    monkeypatch.setattr(mw, "_build_confirmation", fake_builder)
    _ScriptedBox.answer = QMessageBox.StandardButton.Cancel

    dispatched = mw.MainWindow._confirm_force_stop(window, "com.example.app")

    assert dispatched is False  # cancel must never dispatch the action
    text = captured[0].text()
    assert "This will stop:" in text
    assert HOSTILE in text
    assert "com.example.app" in text
    assert "Force Stop the application?" in text


def test_apps_action_prompt_plain_text_and_continue_wording(qtapp, monkeypatch):
    captured: list[QMessageBox] = []

    def fake_builder(parent, title, text):
        box = _ScriptedBox()
        box.answer = QMessageBox.StandardButton.Yes  # per-instance, no leakage
        box.setText(text)
        captured.append(box)
        return box

    monkeypatch.setattr(mw, "_build_confirmation", fake_builder)

    ok = mw.MainWindow._confirm_apps_action(
        SimpleNamespace(), "uninstall", "com.example.app",
        "Uninstall Application?",
    )

    assert ok is True
    assert "Continue?" in captured[0].text()
    assert "com.example.app" in captured[0].text()


def test_benign_label_round_trips_literally(qtapp):
    box = mw._build_confirmation(None, "Title", "WhatsApp")
    assert box.text() == "WhatsApp"
    assert box.textFormat() == Qt.TextFormat.PlainText


def test_dynamic_informationals_are_plain_text_too(qtapp):
    box = mw._build_information(None, "Action not run", "<b>not</b> run: com.a.b")

    assert box.textFormat() == Qt.TextFormat.PlainText
    assert "<b>not</b> run: com.a.b" == box.text()
    assert box.standardButtons() == QMessageBox.StandardButton.Ok


def test_show_information_executes_the_built_box(qtapp, monkeypatch):
    executed: list[str] = []

    class _QuietBox:
        def __init__(self, text: str) -> None:
            self._text = text

        def exec(self) -> QMessageBox.StandardButton:
            executed.append(self._text)
            return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(
        mw, "_build_information", lambda parent, title, text: _QuietBox(text)
    )

    mw._show_information(None, "Action not run", "gated message")

    assert executed == ["gated message"]


# --------------------------------------------------------------------------
# 5. Setup panel: raw detail echoes stay literal
# --------------------------------------------------------------------------

def test_setup_panel_detail_message_is_plain_text(qtapp):
    from android_task_manager.gui.monitor import ConnectionState

    panel = SetupPanel()
    panel.show_state(ConnectionState.ADB_ERROR, HOSTILE)

    assert panel._message.textFormat() == Qt.TextFormat.PlainText
    assert panel._message.text() == HOSTILE


# --------------------------------------------------------------------------
# 6. Process inspector: device-controlled name / cmdline stay literal
# --------------------------------------------------------------------------

def _snapshot(name: str, command_line: str) -> ProcessInspectionSnapshot:
    return ProcessInspectionSnapshot(
        pid=1, name=name, uid=10001, state="S", threads=2, priority=10,
        nice=0, virtual_memory_kb=1, resident_memory_kb=1, rss_anon_kb=1,
        rss_file_kb=0, shared_memory_kb=0, command_line=command_line,
        cpu_percent=None, memory_percent=None, io_read_bytes=None,
        io_write_bytes=None, timestamp=0.0,
    )


def test_inspector_process_name_and_command_line_stay_literal(qtapp):
    widget = ProcessInspectorWidget()

    widget.set_snapshot(_snapshot(HOSTILE, f"/system/bin/{HOSTILE} --flag"))

    assert widget._title.textFormat() == Qt.TextFormat.PlainText
    assert HOSTILE in widget._title.text()
    assert widget._command_line.textFormat() == Qt.TextFormat.PlainText
    assert f"/system/bin/{HOSTILE} --flag" in widget._command_line.text()


def test_inspector_status_and_subtitle_plain_text(qtapp):
    widget = ProcessInspectorWidget()
    # Verified-identity context: the result belongs to THIS process only.
    widget.set_packages({"com.example.app"})
    widget.set_snapshot(_snapshot("com.example.app", "/system/bin/app"))

    widget.show_action_result(
        ActionResult(
            action="force_stop", package_name="com.example.app", success=True,
            message=f"stopped {HOSTILE}", target="com.example.app",
        )
    )
    assert widget._status.textFormat() == Qt.TextFormat.PlainText
    assert HOSTILE in widget._status.text()

    widget.set_gone(1, HOSTILE)
    assert widget._subtitle.textFormat() == Qt.TextFormat.PlainText
    assert HOSTILE in widget._subtitle.text()
