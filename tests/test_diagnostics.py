"""Diagnostics core tests: setup, rotation, redaction, helpers, export.

Everything runs against scratch directories via ``ATMAN_LOG_DIR`` and
``reset_logging``/``setup_logging`` — no real log location is touched and
no telemetry leaves the machine.
"""

from __future__ import annotations

import logging

import pytest

from android_task_manager import __version__
from android_task_manager.core import diagnostics
from android_task_manager.core.diagnostics import (
    export_diagnostics,
    format_exception,
    log_expected_failure,
    log_file_path,
    log_unexpected_failure,
    redact,
    register_secret,
    reset_logging,
    setup_logging,
    traceback_text,
)

_LOGGER = logging.getLogger("android_task_manager")


@pytest.fixture(autouse=True)
def _isolated_logging(tmp_path, monkeypatch):
    """Point every log operation at a fresh scratch dir, reset between tests."""
    monkeypatch.setenv("ATMAN_LOG_DIR", str(tmp_path / "logs"))
    reset_logging()
    yield tmp_path / "logs"
    reset_logging()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_setup_logging_creates_file_and_header(_isolated_logging) -> None:
    setup_logging()
    path = log_file_path()
    assert path.parent == _isolated_logging
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "diagnostic logging started" in content


def test_setup_logging_is_idempotent(_isolated_logging) -> None:
    first = setup_logging()
    assert setup_logging() == first
    # Repeated setup never stacks an extra file handler (pytest capture
    # handlers may also be attached, so count by type).
    file_handlers = [
        handler
        for handler in _LOGGER.handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    setup_logging()
    assert len(file_handlers) == 1


def test_setup_logging_levels(_isolated_logging) -> None:
    setup_logging(level=logging.INFO)
    _LOGGER.debug("quiet detail")
    _LOGGER.info("visible info")
    content = log_file_path().read_text(encoding="utf-8")
    assert "visible info" in content
    assert "quiet detail" not in content


def test_setup_logging_debug_level_writes_debug(_isolated_logging) -> None:
    setup_logging(level=logging.DEBUG)
    _LOGGER.debug("debug detail")
    assert "debug detail" in log_file_path().read_text(encoding="utf-8")


def test_reset_logging_tears_down(_isolated_logging) -> None:
    setup_logging()
    reset_logging()
    assert _LOGGER.handlers == []
    # After a reset, setup configures a fresh pipeline (new dir).
    other = _isolated_logging / "again"
    setup_logging(other)
    assert log_file_path().parent == other


def test_log_file_path_before_setup_uses_default_dir(_isolated_logging) -> None:
    assert log_file_path().parent == _isolated_logging


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, secret_part",
    [
        ("password=hunter2", "hunter2"),
        ("PASSWORD: secret", "secret"),
        ("api_key=sk-abc123", "sk-abc123"),
        ("token = xyz", "xyz"),
        ("api-key = abc", "abc"),
    ],
)
def test_redact_credentials(message, secret_part) -> None:
    assert secret_part not in redact(message)
    assert "<redacted>" in redact(message)


def test_redact_bearer_and_known_token_shapes() -> None:
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in redact("auth: Bearer abcdefghijklmnopqrstuvwxyz")
    assert "sk-0123456789abcdef0123456789abcdef" not in redact("key=sk-0123456789abcdef0123456789abcdef")
    assert "ghp_0123456789abcdefghij0123456789abcdefghij" not in redact("ghp_0123456789abcdefghij0123456789abcdefghij")


def test_redact_mac_addresses() -> None:
    assert "00:1b:44:11:3a:b7" not in redact("wlan mac 00:1b:44:11:3a:b7")


def test_redact_registered_secrets() -> None:
    register_secret("FAKE-SERIAL-123")
    assert "FAKE-SERIAL-123" not in redact("device FAKE-SERIAL-123 connected")
    assert redact("nothing to hide here") == "nothing to hide here"


def test_register_secret_ignores_short_and_duplicate_values() -> None:
    register_secret("ab")
    register_secret(None)
    register_secret("")
    assert "ab" in redact("ab")  # too short to be masked
    register_secret("SERIAL-X")
    register_secret("SERIAL-X")
    assert diagnostics._secrets.count("SERIAL-X") == 1  # duplicates ignored


def test_registered_secrets_are_bounded() -> None:
    for index in range(80):
        register_secret(f"secret-{index:04d}")
    assert len(diagnostics._secrets) <= 64


def test_redacting_formatter_scrubs_records(_isolated_logging) -> None:
    setup_logging()
    _LOGGER.warning("token=supersecretvalue leaked")
    content = log_file_path().read_text(encoding="utf-8")
    assert "supersecretvalue" not in content
    assert "<redacted>" in content


# ---------------------------------------------------------------------------
# Exception helpers
# ---------------------------------------------------------------------------


def test_format_exception_summary() -> None:
    assert format_exception(RuntimeError("boom")) == "RuntimeError: boom"
    assert format_exception(ValueError("")) == "ValueError"


def test_traceback_text_contains_frames() -> None:
    try:
        raise ValueError("bad value")
    except ValueError as exc:
        text = traceback_text(exc)
    assert text.startswith("Traceback (most recent call last)")
    assert "ValueError: bad value" in text


# ---------------------------------------------------------------------------
# Failure logging helpers
# ---------------------------------------------------------------------------


def test_log_expected_failure_writes_warning_without_traceback(_isolated_logging) -> None:
    setup_logging()
    log_expected_failure("baseline", "save", RuntimeError("expected"))
    content = log_file_path().read_text(encoding="utf-8")
    assert "baseline failed during save" in content
    assert "RuntimeError: expected" in content
    assert "Traceback" not in content


def test_log_unexpected_failure_writes_traceback(_isolated_logging) -> None:
    setup_logging()
    try:
        raise KeyError("missing key")
    except KeyError as exc:
        log_unexpected_failure("action", "run", exc)
    content = log_file_path().read_text(encoding="utf-8")
    assert "action raised unexpectedly during run" in content
    assert "Traceback (most recent call last)" in content
    assert "KeyError: 'missing key'" in content


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_diagnostics_to_target(_isolated_logging) -> None:
    setup_logging()
    _LOGGER.warning("token=supersecretvalue leaked")
    target = _isolated_logging / "report.txt"
    written = export_diagnostics(target)
    assert written == target
    content = target.read_text(encoding="utf-8")
    assert "Android Task Manager — diagnostic report" in content
    assert f"android-task-manager {__version__}" in content
    assert "--- Recent log lines ---" in content
    assert "supersecretvalue" not in content  # redaction applies to the report too


def test_export_diagnostics_default_target_is_timestamped(_isolated_logging) -> None:
    setup_logging()
    written = export_diagnostics()
    assert written.parent == _isolated_logging
    assert written.name.startswith("diagnostics-")
    assert written.name.endswith(".txt")
    assert written.exists()


def test_export_without_log_file_reports_honestly(_isolated_logging) -> None:
    reset_logging()  # no setup: nothing written yet
    _isolated_logging.mkdir(parents=True, exist_ok=True)
    target = _isolated_logging / "report.txt"
    content = export_diagnostics(target).read_text(encoding="utf-8")
    assert "(no log file exists yet)" in content