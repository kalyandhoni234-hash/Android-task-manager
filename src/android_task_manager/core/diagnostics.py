"""Diagnostic logging for Android Task Manager — local-only, no telemetry.

This module is the application's observability spine:

* **Application logging** — one package logger (``android_task_manager``)
  that every module-level logger propagates into, with the standard
  DEBUG/INFO/WARNING/ERROR levels.
* **Bounded rotating log files** — 512 KiB per file, 3 backups, on the
  local machine (``%LOCALAPPDATA%\\AndroidTaskManager\\logs`` on Windows,
  ``~/.local/share/android-task-manager/logs`` elsewhere; override with the
  ``ATMAN_LOG_DIR`` environment variable, which tests use).
* **Structured messages** — ``timestamp level module: message`` with
  operation names and, for failures, the exception type and message.
* **Sensitive-information redaction** — common token/password/API-key/MAC
  shapes are scrubbed from every formatted line, and explicit secrets
  (e.g. device serials) can be registered so they are never written.
* **Diagnostic export** — the user can write a local report (version,
  environment, recent log lines) to a destination they choose. Nothing is
  ever uploaded; there is no telemetry.

The logging layer is deliberately conservative: the ADB layer logs
*operations*, never raw device output; serials are registered as secrets
at discovery time; and no IMEI / SIM / token / password / API key is ever
logged by any component.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import sys
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .. import __version__

#: Package-wide logger name; child loggers (``android_task_manager.*``)
#: propagate into it, so one file handler serves the whole app.
LOGGER_NAME = "android_task_manager"

#: Log file name inside the log directory.
_LOG_FILE_NAME = "android-task-manager.log"
#: Rotation budget: 512 KiB per file, 3 backup files.
_MAX_BYTES = 512 * 1024
_BACKUP_COUNT = 3
#: How many trailing log lines a diagnostic export includes.
_EXPORT_LINES = 500
#: Environment override for the log directory (tests use it).
_ENV_LOG_DIR = "ATMAN_LOG_DIR"
#: Bounded registry of registered secrets, oldest evicted first.
_MAX_SECRETS = 64

#: Path of the currently configured log file (None until setup_logging).
_configured_path: Path | None = None
#: Values registered for redaction (device serials, tokens, ...).
_secrets: list[str] = []

#: Shapes that are never written into logs. Patterns are deliberately
#: conservative: a false positive hides a token-shaped substring, which is
#: far safer than leaking one.
_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # password / passwd / secret / token / api_key=... or :...
    re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\b\s*[=:]\s*\S+"),
    # HTTP Authorization bearer tokens.
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    # Well-known token shapes: sk-... (OpenAI-style), ghp_... / github_pat_...
    # (GitHub), xoxb-... (Slack).
    re.compile(r"\b(?:sk-[a-z0-9]{16,}|ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|xox[baprs]-[a-z0-9-]{10,})\b"),
    # MAC addresses: 6 colon-separated hex octets.
    re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
)

_MASK = "<redacted>"


def default_log_dir() -> Path:
    """The local directory diagnostic logs are written to."""
    env = os.environ.get(_ENV_LOG_DIR)
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "AndroidTaskManager" / "logs"
    return Path.home() / ".local" / "share" / "android-task-manager" / "logs"


def log_file_path() -> Path:
    """The log file the app writes to (configured path, or the default)."""
    return _configured_path or default_log_dir() / _LOG_FILE_NAME


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def redact(text: str) -> str:
    """Scrub sensitive shapes and registered secrets from *text*."""
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub(_MASK, text)
    # Longest secrets first, so a secret that embeds another is fully masked.
    for secret in sorted((s for s in _secrets if len(s) >= 4), key=len, reverse=True):
        text = text.replace(secret, _MASK)
    return text


def register_secret(value: str | None) -> None:
    """Register *value* so it is scrubbed from every formatted log line.

    The ADB layer registers each device serial it sees; tokens, keys and
    similar identifiers can be registered the same way. The registry is
    bounded — oldest entries are evicted first.
    """
    if not value:
        return
    value = value.strip()
    if not value or value in _secrets:
        return
    _secrets.append(value)
    if len(_secrets) > _MAX_SECRETS:
        del _secrets[: len(_secrets) - _MAX_SECRETS]


class RedactingFormatter(logging.Formatter):
    """Formatter that scrubs every formatted line before it is written."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_logging(log_dir: Path | str | None = None, level: int = logging.INFO) -> Path:
    """Configure the application logger once; returns the log file path.

    Idempotent: the second call returns the already-configured path and
    never stacks duplicate handlers. ``level`` applies to the file handler;
    the console handler always stays at WARNING so dashboards stay clean.
    """
    global _configured_path
    if _configured_path is not None:
        return _configured_path

    directory = Path(log_dir) if log_dir is not None else default_log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _LOG_FILE_NAME

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = RedactingFormatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    logger.addHandler(console)

    _configured_path = path
    logging.getLogger(LOGGER_NAME).info("diagnostic logging started at %s", path)
    return path


def reset_logging() -> None:
    """Tear down the configured handlers (test helper; also on shutdown).

    After a reset, ``setup_logging`` configures a fresh pipeline; until
    then records are dropped silently, which is the pre-setup behavior.
    """
    global _configured_path
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _configured_path = None


# ---------------------------------------------------------------------------
# Exception helpers
# ---------------------------------------------------------------------------


def format_exception(exc: BaseException) -> str:
    """One-line ``Type: message`` summary for a failure (no traceback)."""
    name = type(exc).__name__
    message = str(exc).strip()
    return f"{name}: {message}" if message else name


def traceback_text(exc: BaseException) -> str:
    """The full formatted traceback of *exc* as a string."""
    return "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ).strip()


# ---------------------------------------------------------------------------
# Worker observability helpers
# ---------------------------------------------------------------------------


def log_expected_failure(component: str, operation: str, exc: BaseException) -> None:
    """Log a typed, expected failure (e.g. an ADB exception) at WARNING.

    Expected failures carry the typed exception summary; no traceback is
    needed because the failure is part of the normal state machine (the
    GUI already maps it to an honest error state).
    """
    logging.getLogger(LOGGER_NAME).warning(
        "%s failed during %s: %s",
        component,
        operation,
        format_exception(exc),
    )


def log_unexpected_failure(component: str, operation: str, exc: BaseException) -> None:
    """Log an unexpected worker exception at ERROR with its full traceback.

    A worker bug must never crash the GUI, but it must be observable: the
    traceback lands in the rotating diagnostic log, and the user receives
    the worker's regular failure signal.
    """
    logging.getLogger(LOGGER_NAME).error(
        "%s raised unexpectedly during %s: %s",
        component,
        operation,
        format_exception(exc),
        exc_info=exc,
    )


# ---------------------------------------------------------------------------
# Diagnostic export
# ---------------------------------------------------------------------------


def export_diagnostics(target: Path | str | None = None, *, lines: int = _EXPORT_LINES) -> Path:
    """Write a local-only diagnostic report; returns the written path.

    ``target`` is a user-selected destination. When omitted, the report is
    written next to the log file with a timestamped name. The report stays
    on this machine — nothing is uploaded, and no telemetry exists.
    """
    now = datetime.now(timezone.utc)
    if target is None:
        path = default_log_dir() / f"diagnostics-{now:%Y%m%d-%H%M%S}.txt"
    else:
        path = Path(target)

    header = [
        "Android Task Manager — diagnostic report",
        f"Generated (UTC):  {now:%Y-%m-%d %H:%M:%S}",
        f"Application:      android-task-manager {__version__}",
        f"Python:           {sys.version.split()[0]}",
        f"Executable:       {sys.executable}",
        f"Platform:         {platform.platform()}",
        f"Machine:          {platform.machine()}",
        f"Log file:         {log_file_path()}",
        "",
        "This report was written locally and never leaves this machine.",
        "",
        "--- Recent log lines ---",
    ]
    body = _read_tail(log_file_path(), lines)
    path.write_text("\n".join([*header, *body, ""]), encoding="utf-8")
    return path


def _read_tail(path: Path, lines: int) -> list[str]:
    """The last *lines* of *path*, or an honest note when unreadable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ["(no log file exists yet)"]
    return text.splitlines()[-lines:]