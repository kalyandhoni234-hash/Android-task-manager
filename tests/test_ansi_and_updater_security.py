"""Focused RED tests for Priority #10: ANSI injection + updater URL validation.

Two security gaps:

AREA 1 — ANSI escape sequences survive into ps/cmdline parsers and reach
the GUI.  While widgets use PlainText (preventing visual formatting
attacks), the defense-in-depth contract requires stripping at the parser
boundary.

AREA 2 — The updater banner opens whatever URL the GitHub API returns,
with no scheme or host validation.  A compromised API response could
cause `javascript:` or `file:` URLs to be opened.
"""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.updater import check as check_module

# =========================================================================
# AREA 1: ANSI escape sequences in process output
# =========================================================================

_ANSI_PROCESS_NAME = "com.\x1b[31mhidden\x1b[0m.app"
_ANSI_CMDLINE = "/system/bin/app\x1b[2K --flag=\x1b[32msecret\x1b[0m"


class TestPsParserStripsAnsi:
    """parse_ps_output must strip ANSI sequences from process names."""

    def test_ansi_in_ps_name_is_stripped(self) -> None:
        from android_task_manager.process.parser import parse_ps_output

        text = f"PID PPID UID NAME\n1000 1 1000 {_ANSI_PROCESS_NAME}\n"
        result = parse_ps_output(text)
        assert len(result) == 1
        assert "\x1b" not in result[0].name

    def test_clean_ps_name_unchanged(self) -> None:
        from android_task_manager.process.parser import parse_ps_output

        text = "PID PPID UID NAME\n1000 1 1000 com.normal.app\n"
        result = parse_ps_output(text)
        assert result[0].name == "com.normal.app"


class TestCmdlineParserStripsAnsi:
    """parse_cmdline must strip ANSI sequences from command lines."""

    def test_ansi_in_cmdline_is_stripped(self) -> None:
        from android_task_manager.process.inspector_parser import parse_cmdline

        result = parse_cmdline(_ANSI_CMDLINE)
        assert result is not None
        assert "\x1b" not in result

    def test_clean_cmdline_unchanged(self) -> None:
        from android_task_manager.process.inspector_parser import parse_cmdline

        assert parse_cmdline("/system/bin/app --flag=value") == "/system/bin/app --flag=value"


# =========================================================================
# AREA 2: Updater URL validation
# =========================================================================


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


class TestUpdateBannerUrlValidation:
    """The update banner must not open non-http(s) URLs."""

    def test_banner_does_not_open_javascript_url(self, qtapp) -> None:
        from android_task_manager.gui.update_banner import UpdateBanner

        banner = UpdateBanner()
        banner._url = "javascript:alert(1)"
        opened: list = []
        with patch(
            "android_task_manager.gui.update_banner.QDesktopServices.openUrl",
            lambda url: opened.append(url),
        ):
            banner._open_release()
        assert not opened

    def test_banner_does_not_open_file_url(self, qtapp) -> None:
        from android_task_manager.gui.update_banner import UpdateBanner

        banner = UpdateBanner()
        banner._url = "file:///etc/passwd"
        opened: list = []
        with patch(
            "android_task_manager.gui.update_banner.QDesktopServices.openUrl",
            lambda url: opened.append(url),
        ):
            banner._open_release()
        assert not opened

    def test_banner_opens_https_url(self, qtapp) -> None:
        from android_task_manager.gui.update_banner import UpdateBanner

        banner = UpdateBanner()
        banner._url = "https://github.com/release"
        opened: list = []
        with patch(
            "android_task_manager.gui.update_banner.QDesktopServices.openUrl",
            lambda url: opened.append(url),
        ):
            banner._open_release()
        assert len(opened) == 1

    def test_banner_does_not_open_empty_url(self, qtapp) -> None:
        from android_task_manager.gui.update_banner import UpdateBanner

        banner = UpdateBanner()
        banner._url = ""
        opened: list = []
        with patch(
            "android_task_manager.gui.update_banner.QDesktopServices.openUrl",
            lambda url: opened.append(url),
        ):
            banner._open_release()
        assert not opened

    def test_banner_does_not_open_data_url(self, qtapp) -> None:
        from android_task_manager.gui.update_banner import UpdateBanner

        banner = UpdateBanner()
        banner._url = "data:text/html,<script>alert(1)</script>"
        opened: list = []
        with patch(
            "android_task_manager.gui.update_banner.QDesktopServices.openUrl",
            lambda url: opened.append(url),
        ):
            banner._open_release()
        assert not opened


class TestUpdaterUrlValidation:
    """fetch_latest_release_tag must reject non-http(s) URLs from the API."""

    def _mock_urlopen(self, tag: str, url: str):
        """Return a context-manager factory that yields a fake API response."""
        import json as _json

        payload = _json.dumps({"tag_name": tag, "html_url": url}).encode()

        class _FakeResp:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return None
            def read(self):
                return payload

        return _FakeResp()

    def test_fetch_rejects_javascript_url(self, monkeypatch) -> None:
        from android_task_manager.updater.check import fetch_latest_release_tag

        monkeypatch.setattr(
            check_module, "_urlopen",
            lambda req, timeout: self._mock_urlopen("v0.3.0", "javascript:alert(1)"),
        )
        tag, url = fetch_latest_release_tag(timeout_seconds=1.0)
        assert url is None

    def test_fetch_rejects_file_url(self, monkeypatch) -> None:
        from android_task_manager.updater.check import fetch_latest_release_tag

        monkeypatch.setattr(
            check_module, "_urlopen",
            lambda req, timeout: self._mock_urlopen("v0.3.0", "file:///etc/passwd"),
        )
        tag, url = fetch_latest_release_tag(timeout_seconds=1.0)
        assert url is None

    def test_fetch_rejects_data_url(self, monkeypatch) -> None:
        from android_task_manager.updater.check import fetch_latest_release_tag

        monkeypatch.setattr(
            check_module, "_urlopen",
            lambda req, timeout: self._mock_urlopen("v0.3.0", "data:text/html,<script>"),
        )
        tag, url = fetch_latest_release_tag(timeout_seconds=1.0)
        assert url is None

    def test_fetch_accepts_https_url(self, monkeypatch) -> None:
        from android_task_manager.updater.check import fetch_latest_release_tag

        monkeypatch.setattr(
            check_module, "_urlopen",
            lambda req, timeout: self._mock_urlopen("v0.3.0", "https://github.com/release"),
        )
        tag, url = fetch_latest_release_tag(timeout_seconds=1.0)
        assert tag == "v0.3.0"
        assert url == "https://github.com/release"

    def test_fetch_rejects_empty_url(self, monkeypatch) -> None:
        from android_task_manager.updater.check import fetch_latest_release_tag

        monkeypatch.setattr(
            check_module, "_urlopen",
            lambda req, timeout: self._mock_urlopen("v0.3.0", ""),
        )
        tag, url = fetch_latest_release_tag(timeout_seconds=1.0)
        assert url is None
