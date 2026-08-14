"""ADB discovery tests: priority order, validation and fallbacks.

Pure filesystem tests (no real adb, no device): every candidate is a plain
file created under ``tmp_path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from android_task_manager.adb.discovery import find_adb, is_valid_adb

_ADB = "adb.exe" if sys.platform == "win32" else "adb"


def _make(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake", encoding="utf-8")
    return path


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        "PATH": str(tmp_path / "bin"),
        "ANDROID_HOME": str(tmp_path / "sdk"),
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "local"),
    }


def test_explicit_path_wins_over_everything(tmp_path: Path) -> None:
    explicit = _make(tmp_path / "custom" / _ADB)
    _make(tmp_path / "bin" / _ADB)
    found = find_adb(explicit=str(explicit), env=_env(tmp_path))
    assert found == str(explicit.resolve())


def test_invalid_explicit_is_skipped_and_search_continues(tmp_path: Path) -> None:
    env_adb = _make(tmp_path / "bin" / _ADB)
    found = find_adb(explicit=str(tmp_path / "nope" / _ADB), env=_env(tmp_path))
    assert found == str(env_adb.resolve())


def test_invalid_explicit_directory_ignored(tmp_path: Path) -> None:
    (tmp_path / "dir" / _ADB).mkdir(parents=True)  # a directory, not a file
    assert find_adb(explicit=str(tmp_path / "dir" / _ADB), env={}) is None


def test_bundled_beside_executable_wins_over_environment(tmp_path: Path, monkeypatch) -> None:
    bundled = _make(tmp_path / "dist" / _ADB)
    _make(tmp_path / "bin" / _ADB)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "AndroidTaskManager.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "dist"), raising=False)
    found = find_adb(env=_env(tmp_path))
    assert found == str(bundled.resolve())


def test_meipass_extraction_dir_also_checked(tmp_path: Path, monkeypatch) -> None:
    bundled = _make(tmp_path / "mei" / _ADB)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "AndroidTaskManager.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)
    found = find_adb(env={})
    assert found == str(bundled.resolve())


def test_path_fallback(tmp_path: Path) -> None:
    path_adb = _make(tmp_path / "bin" / _ADB)
    found = find_adb(env=_env(tmp_path))
    assert found == str(path_adb.resolve())


def test_android_home_fallback(tmp_path: Path) -> None:
    sdk_adb = _make(tmp_path / "sdk" / "platform-tools" / _ADB)
    env = {
        "PATH": str(tmp_path / "missing-bin"),
        "ANDROID_HOME": str(tmp_path / "sdk"),
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    found = find_adb(env=env)
    assert found == str(sdk_adb.resolve())


def test_localappdata_fallback(tmp_path: Path) -> None:
    local_adb = _make(tmp_path / "local" / "Android" / "Sdk" / "platform-tools" / _ADB)
    found = find_adb(env=_env(tmp_path))
    assert found == str(local_adb.resolve())


def test_nothing_found_returns_none(tmp_path: Path) -> None:
    env = {
        "PATH": str(tmp_path / "missing"),
        "ANDROID_HOME": str(tmp_path / "missing-sdk"),
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "missing-local"),
    }
    assert find_adb(env=env) is None
    assert find_adb(explicit=None, env=env) is None


def test_unfrozen_run_has_no_bundled_candidates(tmp_path: Path, monkeypatch) -> None:
    _make(tmp_path / "bin" / _ADB)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    found = find_adb(explicit=None, env=_env(tmp_path))
    assert found == str((tmp_path / "bin" / _ADB).resolve())


def test_is_valid_adb_rejects_none_missing_and_directories(tmp_path: Path) -> None:
    assert is_valid_adb(None) is False
    assert is_valid_adb("") is False
    assert is_valid_adb(str(tmp_path / "missing" / _ADB)) is False
    (tmp_path / "dir" / _ADB).mkdir(parents=True)
    assert is_valid_adb(str(tmp_path / "dir" / _ADB)) is False


def test_is_valid_adb_accepts_real_file(tmp_path: Path) -> None:
    adb = _make(tmp_path / _ADB)
    assert is_valid_adb(str(adb)) is True