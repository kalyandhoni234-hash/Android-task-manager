"""Persistent baseline storage: one baseline per device, atomic writes.

The store lives entirely on the user's machine (a versioned JSON envelope
per device serial, keyed by the ADB serial under ``user_data_dir()``). It
adds no ADB traffic, never touches the device, and never uses pickle —
the on-disk format is the same deterministic JSON the session export
already produces (``snapshot_to_dict`` / ``snapshot_from_dict``), wrapped
in a small envelope so a future schema change is detectable.

Design rules:

* **Atomicity.** ``save`` writes to a temp file in the same directory,
  flushes it to disk and then ``os.replace``s it over the target — a crash
  mid-write never leaves a torn baseline.
* **Honest ``load``.** Missing files, corrupt JSON, an unsupported schema,
  a wrong device serial and permission errors all yield ``None`` (the
  caller falls back to the normal empty state) — never an exception and
  never a fabricated baseline.
* **Privacy.** The file content mirrors the session export: process/socket
  identities with UIDs and the device serial. Nothing is uploaded; the
  store never reads or writes outside ``user_data_dir()``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .export import snapshot_from_dict, snapshot_to_dict
from .models import BaselineSnapshot

#: On-disk envelope version. Bump only when the envelope shape changes.
SCHEMA_VERSION = 1

#: The envelope marker (detects files from other tools / accidental data).
KIND = "baseline"

_FILENAME_PREFIX = "baseline-"
_MAX_TOKEN_LEN = 40
_FILENAME_SAFE = re.compile(r"[^0-9A-Za-z._-]")
_DOT_RUNS = re.compile(r"\.{2,}")


def user_data_dir(app_name: str = "AndroidTaskManager") -> Path:
    """The per-user data directory for this app, on every platform.

    Windows: ``%LOCALAPPDATA%\\<app_name>`` (with a ``~\\AppData\\Local``
    fallback when the variable is unset). macOS: ``~/Library/Application
    Support/<app_name>``. Linux: ``$XDG_DATA_HOME/<app_name>`` or
    ``~/.local/share/<app_name>``. Callers create the directory before
    writing; this function never touches the filesystem.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / app_name
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / app_name


def sanitize_identifier(value: str) -> str:
    """Filesystem-safe token from a device serial: only ``[0-9A-Za-z._-]``.

    Underscores replace anything else and the result is length-capped so a
    hostile/unusual serial can never produce a path traversal or an
    oversized filename.
    """
    cleaned = _FILENAME_SAFE.sub("_", value).strip("._")
    cleaned = _DOT_RUNS.sub(".", cleaned).strip("._")
    if not cleaned:
        cleaned = "device"
    return cleaned[:_MAX_TOKEN_LEN]


@dataclass(frozen=True)
class BaselineStore:
    """Persist one baseline snapshot per device serial under *directory*."""

    directory: Path

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def path_for(self, serial: str) -> Path:
        """The store file for one device: ``baseline-<sanitized>.json``."""
        return self.directory / f"{_FILENAME_PREFIX}{sanitize_identifier(serial)}.json"

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, snapshot: BaselineSnapshot) -> Path:
        """Atomically persist *snapshot*; returns the written path.

        Raises ``OSError`` when the directory cannot be created or the file
        cannot be written — callers surface that honestly instead of
        pretending the baseline survived.
        """
        path = self.path_for(snapshot.device_serial)
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "device_serial": snapshot.device_serial,
            "created_at": snapshot.created_at.isoformat(),
            "baseline": snapshot_to_dict(snapshot),
        }
        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        temp = path.with_name(f"{path.name}.tmp")
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        return path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self, serial: str) -> BaselineSnapshot | None:
        """Load the baseline stored for *serial*, or ``None``.

        Every failure mode (missing file, corrupt JSON, unsupported schema,
        wrong device, unreadable file) maps to ``None`` — a store problem
        must never crash the GUI or invent data.
        """
        path = self.path_for(serial)
        try:
            with open(path, encoding="utf-8") as handle:
                envelope = json.load(handle)
        except (OSError, ValueError):
            return None
        if not isinstance(envelope, dict):
            return None
        if envelope.get("schema_version") != SCHEMA_VERSION:
            return None
        if envelope.get("kind") != KIND:
            return None
        if envelope.get("device_serial") != serial:
            return None
        baseline = envelope.get("baseline")
        if not isinstance(baseline, dict):
            return None
        try:
            snapshot = snapshot_from_dict(baseline)
        except (KeyError, TypeError, ValueError):
            return None
        if snapshot.device_serial != serial:
            return None
        return snapshot

    # ------------------------------------------------------------------
    # Existence
    # ------------------------------------------------------------------

    def exists(self, serial: str) -> bool:
        """True when a readable baseline file exists for *serial*."""
        try:
            return self.path_for(serial).is_file()
        except OSError:
            return False


__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "BaselineStore",
    "sanitize_identifier",
    "user_data_dir",
]