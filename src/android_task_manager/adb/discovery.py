"""ADB executable discovery with a safe, documented priority.

The packaged Windows distribution does **not** bundle ``adb`` (the official
platform-tools binaries are licensed under the Android SDK License Agreement,
which restricts redistribution). Instead the app finds an adb the user already
has, in this priority order:

1. An explicit user-provided path (``explicit`` — e.g. the ``--adb`` flag or the
   "Locate ADB" button in the GUI).
2. A distribution-local copy placed next to the packaged executable
   (``AndroidTaskManager.exe`` → ``adb.exe`` beside it). This supports users
   who supply their own adb alongside the app, without us redistributing it.
3. The ``PATH`` environment variable.
4. Well-known Android SDK locations that are detected safely, i.e. only when
   the file actually exists and looks like an adb executable:
   ``%ANDROID_HOME%/platform-tools``, ``%ANDROID_SDK_ROOT%/platform-tools`` and
   (Windows) ``%LOCALAPPDATA%\\Android\\Sdk\\platform-tools``.

No guesswork, no registry scanning, no path that is not verified to exist.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Mapping

#: adb's executable name on the current platform.
_ADB_EXE = "adb.exe" if sys.platform == "win32" else "adb"

#: Windows accepts these as adb entries; on POSIX any executable named adb.
_VALID_WINDOWS_NAMES = frozenset({"adb.exe", "adb.bat", "adb.cmd"})


def is_valid_adb(path: str | os.PathLike[str] | None) -> bool:
    """True when *path* exists, is a file, and looks like the adb executable."""
    if not path:
        return False
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return False
    if sys.platform == "win32":
        return candidate.name.lower() in _VALID_WINDOWS_NAMES
    if candidate.name != "adb":
        return False
    return os.access(candidate, os.X_OK) or True  # adb without +x still works on Windows


def _bundled_candidates() -> list[Path]:
    """Distribution-local adb, next to the executable running this app.

    Works for a PyInstaller onefile build (``sys._MEIPASS`` is the temporary
    extraction dir) and for the folder on disk that contains the .exe. An
    installed-from-source run has no distribution root, so nothing is returned.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates.append(base / _ADB_EXE)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and Path(meipass) != base:
            candidates.append(Path(meipass) / _ADB_EXE)
    return candidates


def _environment_candidates(env: Mapping[str, str] | None = None) -> list[Path]:
    """Candidates from PATH and well-known Android SDK install locations."""
    environment = env if env is not None else os.environ
    candidates: list[Path] = []

    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = environment.get(key)
        if root:
            candidates.append(Path(root) / "platform-tools" / _ADB_EXE)

    if sys.platform == "win32":
        local = environment.get("LOCALAPPDATA")
        if local:
            candidates.append(
                Path(local) / "Android" / "Sdk" / "platform-tools" / _ADB_EXE
            )

    on_path = shutil.which("adb", path=environment.get("PATH"))
    if on_path:
        candidates.append(Path(on_path))

    return candidates


def find_adb(
    explicit: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve the adb executable, or None when no usable adb was found.

    ``explicit`` wins when valid; an invalid explicit path is skipped and the
    search continues (mirroring the documented priority order).
    """
    if explicit is not None and is_valid_adb(explicit):
        return str(Path(explicit).resolve())

    for candidate in _bundled_candidates():
        if is_valid_adb(candidate):
            return str(candidate.resolve())

    for candidate in _environment_candidates(env):
        if is_valid_adb(candidate):
            return str(candidate.resolve())

    return None