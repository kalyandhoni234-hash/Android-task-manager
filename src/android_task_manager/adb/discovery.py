"""ADB executable discovery with a safe, documented priority.

The packaged Windows distribution does **not** bundle ``adb`` (the official
platform-tools binaries are licensed under the Android SDK License Agreement,
which restricts redistribution). Instead the app finds an adb the user already
has, in this priority order:

1. An explicit user-provided path (``explicit`` — e.g. the ``--adb`` flag or
   the "Locate ADB" button in the GUI).
2. A distribution-local copy placed next to the packaged executable
   (``AndroidTaskManager.exe`` → ``adb.exe`` beside it). This supports users
   who supply their own adb alongside the app, without us redistributing it.
3. ``adb`` on ``PATH`` (Windows-safe lookup via ``shutil.which``).
4. Well-known Android SDK locations, detected safely — i.e. only when the
   file actually exists and looks like an adb executable:
   ``%ANDROID_HOME%/platform-tools``, ``%ANDROID_SDK_ROOT%/platform-tools``,
   (Windows) ``%LOCALAPPDATA%\\Android\\Sdk\\platform-tools`` and
   ``%USERPROFILE%\\AppData\\Local\\Android\\Sdk\\platform-tools``.

No guesswork, no registry scanning, no recursive disk searches, no path that
is not verified to exist. Duplicate candidates (e.g. ``ANDROID_HOME`` and
``ANDROID_SDK_ROOT`` pointing at the same SDK) are eliminated.

Optionally a candidate is verified by running ``adb version`` through the
existing ``ConnectionManager`` (the only component allowed to spawn adb);
discovery itself never executes anything.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Iterator, Mapping

#: adb's executable name on the current platform.
_ADB_EXE = "adb.exe" if sys.platform == "win32" else "adb"

#: Windows accepts these as adb entries; on POSIX any executable named adb.
_VALID_WINDOWS_NAMES = frozenset({"adb.exe", "adb.bat", "adb.cmd"})


def is_valid_adb(path: str | os.PathLike[str] | None) -> bool:
    """True when *path* exists, is a file, and looks like the adb executable.

    This checks only the filesystem shape — it never runs anything. Use a
    validator (see :func:`version_validator`) to additionally confirm that the
    binary actually launches.
    """
    if not path:
        return False
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return False
    if sys.platform == "win32":
        return candidate.name.lower() in _VALID_WINDOWS_NAMES
    if candidate.name != "adb":
        return False
    return os.access(candidate, os.X_OK)


def version_validator(timeout: float = 10.0) -> Callable[[str], bool]:
    """Return a validator that runs ``adb version`` via ConnectionManager.

    Subprocess execution stays inside the ADB layer — discovery only inspects
    filesystems; the validator asks the existing ``ConnectionManager`` to
    launch the candidate. Returns True when ``adb version`` succeeds.
    """
    from .connection import ConnectionManager
    from .exceptions import ADBError

    def validate(path: str) -> bool:
        try:
            ConnectionManager(adb_path=str(path), timeout=timeout).verify_available()
            return True
        except ADBError:
            return False

    return validate


def is_usable_adb(
    path: str | os.PathLike[str] | None,
    validator: Callable[[str], bool] | None = None,
) -> bool:
    """True when *path* looks like adb and (if a validator is given) launches.

    Used by the "Locate ADB" flow: a file is accepted only after it passes the
    existence/name checks **and** the optional execution check.
    """
    if not is_valid_adb(path):
        return False
    if validator is not None:
        try:
            return bool(validator(str(path)))
        except Exception:  # noqa: BLE001 - a broken validator must reject
            return False
    return True


def _bundled_candidates() -> list[Path]:
    """Distribution-local adb, next to the executable running this app.

    Works for a PyInstaller onefile build (``sys._MEIPASS`` is the temporary
    extraction dir) and for the folder on disk that contains the .exe — never
    the current working directory. An installed-from-source run has no
    distribution root, so nothing is returned.
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
    """Candidates from PATH and well-known Android SDK install locations.

    When an explicit ``env`` mapping is provided it fully controls the lookup
    (a missing ``PATH`` key means "no PATH candidate"), so tests are hermetic
    and the caller decides exactly what is discoverable. With ``env=None`` the
    real environment is used.
    """
    environment = env if env is not None else os.environ
    candidates: list[Path] = []

    path_value = environment.get("PATH")
    if path_value:
        on_path = shutil.which("adb", path=path_value)
        if on_path:
            candidates.append(Path(on_path))

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
        profile = environment.get("USERPROFILE")
        if profile:
            candidates.append(
                Path(profile) / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / _ADB_EXE
            )

    return candidates


def _candidates(
    explicit: str | os.PathLike[str] | None,
    env: Mapping[str, str] | None,
) -> Iterator[Path]:
    """Ordered, deduplicated, shape-validated candidates.

    Duplicates (same resolved path, case-insensitive) are emitted once. Only
    candidates that exist and look like adb are yielded; nothing is executed.
    """
    seen: set[str] = set()
    sources: list[Path] = []
    if explicit is not None:
        sources.append(Path(explicit))
    sources.extend(_bundled_candidates())
    sources.extend(_environment_candidates(env))

    for candidate in sources:
        if not is_valid_adb(candidate):
            continue
        key = str(candidate.resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def find_adb(
    explicit: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    validator: Callable[[str], bool] | None = None,
) -> str | None:
    """Resolve the adb executable, or None when no usable adb was found.

    ``explicit`` wins when usable; an explicit path that fails its checks or
    the validator is skipped and the search continues (mirroring the
    documented priority order). When a validator is supplied, only candidates
    it accepts are returned — a real ``adb.exe`` that cannot launch ``adb
    version`` is skipped in favor of the next candidate.
    """
    for candidate in _candidates(explicit, env):
        if validator is not None and not validator(str(candidate)):
            continue
        return str(candidate.resolve())
    return None