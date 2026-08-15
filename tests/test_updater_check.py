"""Update-checker logic tests: version parsing, comparison, fetch, orchestration.

The GitHub API is never contacted — ``_urlopen`` and
``fetch_latest_release_tag`` are mocked throughout, so zero real network
calls occur during the test run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from android_task_manager.updater import (
    UpdateCheckResult,
    VersionParseError,
    check_for_update,
    fetch_latest_release_tag,
    is_newer,
    parse_version,
)

from android_task_manager.updater import check as check_module


class _FakeResponse:
    """Context-manager stand-in for urllib's HTTPResponse."""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _github_payload(tag: str = "v0.3.0", url: str = "https://github.com/release") -> bytes:
    return (
        '{"tag_name": "%s", "html_url": "%s"}'
        % (tag, url)
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# parse_version / is_newer
# ---------------------------------------------------------------------------


class TestVersionComparison:
    def test_is_newer_true_when_latest_is_higher(self) -> None:
        assert is_newer("0.2.0", "0.3.0")
        assert is_newer("0.2.0", "0.2.1")
        assert is_newer("0.9.0", "1.0.0")

    def test_is_newer_false_when_equal(self) -> None:
        assert not is_newer("0.2.0", "0.2.0")

    def test_is_newer_false_when_current_is_higher(self) -> None:
        assert not is_newer("0.3.0", "0.2.0")

    def test_is_newer_handles_v_prefix_consistently(self) -> None:
        assert is_newer("v0.2.0", "0.3.0")
        assert is_newer("0.2.0", "v0.3.0")
        assert not is_newer("v0.2.0", "0.2.0")
        assert not is_newer("v0.3.0", "0.2.0")

    def test_is_newer_false_on_unparseable_version(self) -> None:
        for bad in ("latest", "nightly-build", "", "1.2.3-beta", "v", "1..2"):
            assert not is_newer(bad, "0.2.0")
            assert not is_newer("0.2.0", bad)
            assert not is_newer(bad, bad)

    def test_parse_version_rejects_unparseable_input(self) -> None:
        for bad in ("latest", "nightly-build", "", "1.2.3-beta", "v", "1..2"):
            with pytest.raises(VersionParseError):
                parse_version(bad)

    def test_parse_version_accepts_prefix_and_plain(self) -> None:
        assert parse_version("v0.2.0") == (0, 2, 0)
        assert parse_version("0.2.0") == (0, 2, 0)
        assert parse_version("V1.0.0") == (1, 0, 0)


# ---------------------------------------------------------------------------
# fetch_latest_release_tag (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchLatestReleaseTag:
    def test_fetch_latest_release_tag_success(self, monkeypatch) -> None:
        monkeypatch.setattr(
            check_module,
            "_urlopen",
            lambda request, timeout: _FakeResponse(_github_payload()),
        )
        tag, url = fetch_latest_release_tag(timeout_seconds=1.0)
        assert tag == "v0.3.0"
        assert url == "https://github.com/release"

    def test_fetch_latest_release_tag_network_failure(self, monkeypatch) -> None:
        def boom(request, timeout):
            raise OSError("no route to host")

        monkeypatch.setattr(check_module, "_urlopen", boom)
        assert fetch_latest_release_tag(timeout_seconds=1.0) == (None, None)

    def test_fetch_latest_release_tag_malformed_response(self, monkeypatch) -> None:
        monkeypatch.setattr(
            check_module,
            "_urlopen",
            lambda request, timeout: _FakeResponse(b"not json at all"),
        )
        assert fetch_latest_release_tag(timeout_seconds=1.0) == (None, None)

        monkeypatch.setattr(
            check_module,
            "_urlopen",
            lambda request, timeout: _FakeResponse(b'{"unexpected": "shape"}'),
        )
        assert fetch_latest_release_tag(timeout_seconds=1.0) == (None, None)

        monkeypatch.setattr(
            check_module,
            "_urlopen",
            lambda request, timeout: _FakeResponse(b'{"tag_name": 42, "html_url": "x"}'),
        )
        assert fetch_latest_release_tag(timeout_seconds=1.0) == (None, None)

    def test_fetch_latest_release_tag_timeout(self, monkeypatch) -> None:
        def boom(request, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr(check_module, "_urlopen", boom)
        assert fetch_latest_release_tag(timeout_seconds=1.0) == (None, None)

    def test_fetch_latest_release_tag_non_200_status(self, monkeypatch) -> None:
        monkeypatch.setattr(
            check_module,
            "_urlopen",
            lambda request, timeout: _FakeResponse(b"{}", status=403),
        )
        assert fetch_latest_release_tag(timeout_seconds=1.0) == (None, None)


# ---------------------------------------------------------------------------
# check_for_update (mocked fetch)
# ---------------------------------------------------------------------------


class TestCheckForUpdate:
    def test_check_for_update_reports_available(self, monkeypatch) -> None:
        monkeypatch.setattr(
            check_module,
            "fetch_latest_release_tag",
            lambda: ("v0.3.0", "https://github.com/release/tag/v0.3.0"),
        )
        result = check_for_update("0.2.0")
        assert result.update_available is True
        assert result.latest_version == "v0.3.0"
        assert result.release_url == "https://github.com/release/tag/v0.3.0"
        assert result.current_version == "0.2.0"
        assert result.error is None
        assert isinstance(result, UpdateCheckResult)

    def test_check_for_update_reports_up_to_date(self, monkeypatch) -> None:
        monkeypatch.setattr(
            check_module,
            "fetch_latest_release_tag",
            lambda: ("v0.2.0", "https://github.com/release/tag/v0.2.0"),
        )
        result = check_for_update("0.2.0")
        assert result.update_available is False
        assert result.error is None
        assert result.latest_version == "v0.2.0"

        monkeypatch.setattr(
            check_module,
            "fetch_latest_release_tag",
            lambda: ("v0.1.0", "https://github.com/release/tag/v0.1.0"),
        )
        older = check_for_update("0.2.0")
        assert older.update_available is False
        assert older.error is None

    def test_check_for_update_reports_failure_gracefully(self, monkeypatch) -> None:
        monkeypatch.setattr(check_module, "fetch_latest_release_tag", lambda: (None, None))
        result = check_for_update("0.2.0")
        assert result.update_available is False
        assert result.latest_version is None
        assert result.release_url is None
        assert isinstance(result.error, str) and result.error

    def test_check_for_update_surprising_failure_never_raises(self, monkeypatch) -> None:
        def boom():
            raise RuntimeError("internal bug")

        monkeypatch.setattr(check_module, "fetch_latest_release_tag", boom)
        result = check_for_update("0.2.0")
        assert result.update_available is False
        assert result.latest_version is None
        assert isinstance(result.error, str) and result.error

    def test_check_for_update_records_checked_at(self, monkeypatch) -> None:
        monkeypatch.setattr(
            check_module,
            "fetch_latest_release_tag",
            lambda: ("v0.3.0", "https://github.com/release/tag/v0.3.0"),
        )
        result = check_for_update("0.2.0")
        assert isinstance(result.checked_at, datetime)
        assert result.checked_at.tzinfo == timezone.utc