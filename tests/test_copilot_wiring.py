"""Regression tests for the v0.9.2 manual-validation blockers.

Blocker 1: the main window used a hardcoded ``resize(960, 760)`` that could
push the window's bottom edge behind the Windows taskbar on smaller displays.
Blocker 2: the "Configure API Key" / "Configure Gemini" buttons emitted
signals (``configure_requested`` / ``copilot_manage_requested``) that were
never connected, so the settings dialog never opened and the key could not be
configured at runtime.
"""

import os
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from android_task_manager.copilot.settings import (  # noqa: E402
    CopilotConfig,
    save_config,
)
from android_task_manager.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def qtapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def window(qtapp):
    win = MainWindow()
    yield win
    win.close()


# ---------------------------------------------------------------------------
# Blocker 1: window geometry must stay inside the work area (no taskbar overlap)
# ---------------------------------------------------------------------------


def test_window_fits_inside_work_area(window):
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry()
    geo = window.geometry()
    assert geo.width() <= avail.width()
    assert geo.height() <= avail.height()
    assert geo.x() >= avail.x()
    assert geo.y() >= avail.y()


def test_window_has_minimum_size(window):
    assert window.minimumWidth() >= 700
    assert window.minimumHeight() >= 500


def test_window_clamp_keeps_geometry_in_bounds(window):
    # Force an oversized geometry, then clamp; it must be brought back in.
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry()
    window.resize(avail.width() + 400, avail.height() + 400)
    window._clamp_to_available_geometry()
    geo = window.geometry()
    assert geo.width() <= avail.width()
    assert geo.height() <= avail.height()


# ---------------------------------------------------------------------------
# Blocker 2: Configure API Key must be wired and take effect at runtime
# ---------------------------------------------------------------------------


def test_configure_signals_are_wired(window):
    # The two no-arg configure signals must be connected (Blocker 2 root cause:
    # they were previously emitted but never connected to anything).
    assert window.copilot_page.receivers("2configure_requested()") >= 1
    assert window.settings_page.receivers("2copilot_manage_requested()") >= 1


def test_chat_requested_is_wired(window, monkeypatch):
    worker = MagicMock()
    window._copilot_worker = worker
    import android_task_manager.copilot.settings as cs

    monkeypatch.setattr(cs, "load_config", lambda: CopilotConfig(api_key="AIza-CHAT"))
    window.copilot_page.chat_requested.emit("how do I stop a process?")
    worker.request_chat.assert_called_once()


def test_test_requested_is_wired(window):
    worker = MagicMock()
    window._copilot_worker = worker
    window.settings_page.copilot_test_requested.emit(CopilotConfig(api_key="AIza-TEST"))
    worker.update_config.assert_called_once()
    worker.request_test_connection.assert_called_once()


def test_config_saved_updates_both_pages(window):
    cfg = CopilotConfig(api_key="AIza-SAMPLE")
    window._on_copilot_config_saved(cfg)
    assert window.copilot_page._configured is True
    assert "configured" in window.settings_page._api_status.text().lower()


def test_refresh_copilot_state_uses_persisted_config(window, monkeypatch):
    cfg = CopilotConfig(api_key="AIza-PERSIST")
    import android_task_manager.copilot.settings as cs

    monkeypatch.setattr(cs, "load_config", lambda: cfg)
    window._refresh_copilot_state()
    assert window.copilot_page._configured is True
    assert "configured" in window.settings_page._api_status.text().lower()


def test_config_round_trips_through_disk(window, tmp_path, monkeypatch):
    import android_task_manager.copilot.settings as cs

    monkeypatch.setattr(cs, "_user_config_path", lambda: tmp_path / "copilot-config.json")
    monkeypatch.setattr(cs, "_user_config_dir", lambda: tmp_path)
    save_config(CopilotConfig(api_key="AIza-ROUNDTRIP"))
    window._refresh_copilot_state()
    assert window.copilot_page._configured is True
    assert "configured" in window.settings_page._api_status.text().lower()


def test_copilot_test_routes_to_worker(window):
    worker = MagicMock()
    window._copilot_worker = worker
    cfg = CopilotConfig(api_key="AIza-TEST")
    window._on_copilot_test(cfg)
    worker.update_config.assert_called_once_with(cfg)
    worker.request_test_connection.assert_called_once_with(cfg)


def test_copilot_test_result_routes_without_dialog(window):
    worker = MagicMock()
    window._copilot_worker = worker
    window._copilot_dialog = None
    window._on_copilot_test_result(True, "Connected")
    assert "Connected" in window.settings_page._test_status.text()


def test_copilot_test_result_routes_to_dialog(window):
    window._copilot_dialog = MagicMock()
    window._on_copilot_test_result(False, "Bad key")
    window._copilot_dialog.on_test_result.assert_called_once_with(False, "Bad key")


def test_copilot_chat_without_key_shows_error(window, monkeypatch):
    worker = MagicMock()
    window._copilot_worker = worker
    import android_task_manager.copilot.settings as cs

    monkeypatch.setattr(cs, "load_config", lambda: CopilotConfig(api_key=""))
    window._on_copilot_chat("how do I stop a process?")
    worker.request_chat.assert_not_called()
    # An error system bubble must have been rendered (the layout starts with a
    # stretch, so count >= 2 means a bubble was added).
    assert window.copilot_page._messages_layout.count() >= 2


def test_copilot_chat_with_key_requests_response(window, monkeypatch):
    worker = MagicMock()
    window._copilot_worker = worker
    import android_task_manager.copilot.settings as cs

    monkeypatch.setattr(cs, "load_config", lambda: CopilotConfig(api_key="AIza-CHAT"))
    window._on_copilot_chat("how do I stop a process?")
    worker.update_config.assert_called_once()
    worker.request_chat.assert_called_once()
