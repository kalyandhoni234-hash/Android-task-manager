"""Headless GUI tests for the update banner and its background worker.

Offscreen Qt platform; the GitHub API is mocked throughout, so no real
network call ever happens. Covers: default hidden state, show on update,
silent hide on failure, in-session dismissal, and thread offloading of
the check (same QThread wiring convention the app uses).
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QThread, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from android_task_manager.gui.update_banner import UpdateBanner
from android_task_manager.gui.update_worker import UpdateWorker
from android_task_manager.updater import UpdateCheckResult

from android_task_manager.updater import check as check_module

_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
_RELEASE_URL = "https://github.com/kalyandhoni234-hash/Android-task-manager/releases/tag/v0.3.0"


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _result(
    *,
    update_available: bool = False,
    latest_version: str | None = None,
    release_url: str | None = None,
    error: str | None = None,
) -> UpdateCheckResult:
    return UpdateCheckResult(
        checked_at=_AT,
        current_version="0.2.0",
        latest_version=latest_version,
        update_available=update_available,
        release_url=release_url,
        error=error,
    )


def _buttons(banner: UpdateBanner) -> dict[str, QPushButton]:
    return {button.text(): button for button in banner.findChildren(QPushButton)}


class TestUpdateBanner:
    def test_banner_hidden_by_default(self, qtapp) -> None:
        banner = UpdateBanner()
        assert banner.isHidden()

    def test_banner_shows_when_update_available(self, qtapp) -> None:
        banner = UpdateBanner()
        banner.show_result(
            _result(
                update_available=True,
                latest_version="v0.3.0",
                release_url=_RELEASE_URL,
            )
        )
        assert not banner.isHidden()
        labels = banner.findChildren(QLabel)
        assert any(
            label.text() == "A new version (v0.3.0) is available." for label in labels
        )
        assert "View Release" in _buttons(banner)

    def test_banner_normalizes_unprefixed_latest_version(self, qtapp) -> None:
        banner = UpdateBanner()
        banner.show_result(
            _result(update_available=True, latest_version="0.3.0", release_url=_RELEASE_URL)
        )
        labels = banner.findChildren(QLabel)
        assert any(
            label.text() == "A new version (v0.3.0) is available." for label in labels
        )

    def test_banner_stays_hidden_when_check_failed(self, qtapp) -> None:
        banner = UpdateBanner()
        banner.show_result(_result(error="The update check could not reach the feed."))
        assert banner.isHidden()

    def test_banner_stays_hidden_when_up_to_date(self, qtapp) -> None:
        banner = UpdateBanner()
        banner.show_result(_result(latest_version="v0.2.0", release_url=_RELEASE_URL))
        assert banner.isHidden()

    def test_banner_dismiss_hides_it(self, qtapp) -> None:
        banner = UpdateBanner()
        banner.show_result(
            _result(
                update_available=True,
                latest_version="v0.3.0",
                release_url=_RELEASE_URL,
            )
        )
        assert not banner.isHidden()
        _buttons(banner)["\u00d7"].click()
        assert banner.isHidden()
        banner.show_result(
            _result(
                update_available=True,
                latest_version="v0.4.0",
                release_url=_RELEASE_URL,
            )
        )
        assert banner.isHidden()


class TestUpdateWorker:
    def test_banner_check_runs_on_background_worker_not_main_thread(
        self, qtapp, monkeypatch
    ) -> None:
        main_thread = QThread.currentThread()
        executed_on: list[QThread] = []

        def fake_fetch(timeout_seconds: float = 5.0) -> tuple[str | None, str | None]:
            executed_on.append(QThread.currentThread())
            return "v0.3.0", _RELEASE_URL

        monkeypatch.setattr(check_module, "fetch_latest_release_tag", fake_fetch)

        worker = UpdateWorker(current_version="0.2.0")
        thread = QThread()
        worker.moveToThread(thread)
        received: list[UpdateCheckResult] = []
        done = threading.Event()

        def on_completed(result: UpdateCheckResult) -> None:
            received.append(result)
            done.set()

        worker.check_completed.connect(on_completed)
        thread.start()

        QMetaObject.invokeMethod(
            worker, "request_check", Qt.ConnectionType.QueuedConnection
        )

        deadline = time.monotonic() + 5.0
        while not done.is_set() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        thread.quit()
        thread.wait(3000)

        assert done.is_set()
        assert executed_on, "the check never ran"
        assert executed_on[0] is not main_thread
        assert len(received) == 1
        assert received[0].update_available is True
        assert received[0].latest_version == "v0.3.0"
        assert not worker.is_busy()