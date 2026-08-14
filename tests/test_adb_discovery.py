"""ADB discovery tests: priority order, validation and fallbacks.

Pure filesystem tests (no real adb, no device): every candidate is a plain
file created under ``tmp_path``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from android_task_manager.adb.discovery import (
    find_adb,
    is_usable_adb,
    is_valid_adb,
    version_validator,
)

_ADB = "adb.exe" if sys.platform == "win32" else "adb"


def _make(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake", encoding="utf-8")
    if sys.platform != "win32":
        # A real adb on POSIX is executable; PATH lookup (shutil.which) and
        # is_valid_adb require X_OK, so fixtures must mimic a real binary.
        os.chmod(path, 0o755)
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
    env = _env(tmp_path)
    if sys.platform == "win32":
        # %LOCALAPPDATA%/Android/Sdk is a Windows-only adb location.
        found = find_adb(env=env)
        assert found == str(local_adb.resolve())
    else:
        # On other platforms the Windows SDK env vars must not be consulted:
        # the same env dict yields no candidate (PATH and ANDROID_HOME are
        # empty under this test's file layout).
        assert find_adb(env=env) is None


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


def test_android_sdk_root_fallback(tmp_path: Path) -> None:
    sdk_adb = _make(tmp_path / "sdk2" / "platform-tools" / _ADB)
    env = {
        "PATH": str(tmp_path / "missing-bin"),
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": str(tmp_path / "sdk2"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    found = find_adb(env=env)
    assert found == str(sdk_adb.resolve())


def test_userprofile_fallback(tmp_path: Path) -> None:
    user_adb = _make(tmp_path / "profile" / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / _ADB)
    env = {
        "PATH": str(tmp_path / "missing-bin"),
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "missing-local"),
        "USERPROFILE": str(tmp_path / "profile"),
    }
    if sys.platform == "win32":
        # %USERPROFILE%/AppData/Local/Android/Sdk is a Windows-only location.
        found = find_adb(env=env)
        assert found == str(user_adb.resolve())
    else:
        # Other platforms must ignore the Windows SDK env vars entirely.
        assert find_adb(env=env) is None


def test_duplicate_candidates_are_checked_once(tmp_path: Path) -> None:
    sdk = _make(tmp_path / "sdk" / "platform-tools" / _ADB)
    calls: list[str] = []
    env = {
        "PATH": str(tmp_path / "missing-bin"),
        "ANDROID_HOME": str(tmp_path / "sdk"),
        "ANDROID_SDK_ROOT": str(tmp_path / "sdk"),
        "LOCALAPPDATA": str(tmp_path / "sdk"),  # LOCALAPPDATA=sdk would be a different path shape
        "USERPROFILE": str(tmp_path / "profile"),
    }
    found = find_adb(env=env, validator=lambda p: calls.append(p) or True)
    assert found == str(sdk.resolve())
    assert len(calls) == 1


def test_localappdata_matches_userprofile_appdata_deduplicated(tmp_path: Path) -> None:
    user_adb = _make(tmp_path / "profile" / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / _ADB)
    calls: list[str] = []
    env = {
        "PATH": str(tmp_path / "missing-bin"),
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "profile" / "AppData" / "Local"),
        "USERPROFILE": str(tmp_path / "profile"),
    }
    found = find_adb(env=env, validator=lambda p: calls.append(p) or True)
    if sys.platform == "win32":
        # LOCALAPPDATA and USERPROFILE may reference the same directory; the
        # candidate must be validated exactly once.
        assert found == str(user_adb.resolve())
        assert len(calls) == 1
    else:
        # Windows-only env vars are ignored on other platforms.
        assert found is None
        assert calls == []


def test_validator_rejects_skips_to_next_candidate(tmp_path: Path) -> None:
    _make(tmp_path / "bin" / _ADB)
    sdk_adb = _make(tmp_path / "sdk" / "platform-tools" / _ADB)
    checked: list[str] = []
    env = {
        "PATH": str(tmp_path / "bin"),
        "ANDROID_HOME": str(tmp_path / "sdk"),
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "local"),
    }

    def validator(path: str) -> bool:
        checked.append(path)
        return "sdk" in path  # PATH candidate fails adb version; sdk passes

    found = find_adb(env=env, validator=validator)
    assert found == str(sdk_adb.resolve())
    assert "bin" in checked[0] and checked[0].casefold().endswith(_ADB.casefold())
    assert checked[1] == str(sdk_adb.resolve())


def test_validator_rejects_everything_returns_none(tmp_path: Path) -> None:
    _make(tmp_path / "bin" / _ADB)
    assert find_adb(env=_env(tmp_path), validator=lambda p: False) is None


def test_explicit_with_validator_wins(tmp_path: Path) -> None:
    explicit = _make(tmp_path / "custom" / _ADB)
    _make(tmp_path / "bin" / _ADB)
    found = find_adb(explicit=str(explicit), env=_env(tmp_path), validator=lambda p: True)
    assert found == str(explicit.resolve())


def test_explicit_fails_validator_falls_through(tmp_path: Path) -> None:
    explicit = _make(tmp_path / "custom" / _ADB)
    env_adb = _make(tmp_path / "bin" / _ADB)
    found = find_adb(
        explicit=str(explicit),
        env=_env(tmp_path),
        validator=lambda p: "bin" in p,  # explicit custom path fails the version check
    )
    assert found == str(env_adb.resolve())


def test_cwd_adb_is_never_a_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "AndroidTaskManager.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "dist"), raising=False)
    _make(tmp_path / "cwd" / _ADB)
    monkeypatch.chdir(tmp_path / "cwd")
    assert find_adb(env={}) is None


def test_packaged_exe_dir_ignores_cwd(tmp_path: Path, monkeypatch) -> None:
    bundled = _make(tmp_path / "dist" / _ADB)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dist" / "AndroidTaskManager.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "dist"), raising=False)
    _make(tmp_path / "cwd" / _ADB)
    monkeypatch.chdir(tmp_path / "cwd")
    found = find_adb(env={})
    assert found == str(bundled.resolve())


def test_path_with_existing_dir_but_no_adb_returns_none(tmp_path: Path) -> None:
    real_dir = tmp_path / "plain-dir"
    real_dir.mkdir()
    env = {
        "PATH": str(real_dir),  # exists, but contains no adb
        "ANDROID_HOME": "",
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "missing-local"),
    }
    assert find_adb(env=env) is None


def test_priority_path_before_sdk_roots_before_localappdata(tmp_path: Path) -> None:
    path_adb = _make(tmp_path / "bin" / _ADB)
    sdk_adb = _make(tmp_path / "sdk" / "platform-tools" / _ADB)
    local_adb = _make(tmp_path / "local" / "Android" / "Sdk" / "platform-tools" / _ADB)
    env = {
        "PATH": str(tmp_path / "bin"),
        "ANDROID_HOME": str(tmp_path / "sdk"),
        "ANDROID_SDK_ROOT": "",
        "LOCALAPPDATA": str(tmp_path / "local"),
    }
    assert find_adb(env=env) == str(path_adb.resolve())

    env["PATH"] = str(tmp_path / "missing-bin")
    assert find_adb(env=env) == str(sdk_adb.resolve())

    env["ANDROID_HOME"] = str(tmp_path / "missing-sdk")
    if sys.platform == "win32":
        # %LOCALAPPDATA%/Android/Sdk is the Windows-only last resort.
        assert find_adb(env=env) == str(local_adb.resolve())
    else:
        # Non-Windows platforms have no further candidates after PATH and the
        # SDK root env vars.
        assert find_adb(env=env) is None


def test_is_usable_adb_requires_validator_acceptance(tmp_path: Path) -> None:
    adb = _make(tmp_path / _ADB)
    assert is_usable_adb(str(adb)) is True
    assert is_usable_adb(str(adb), lambda p: True) is True
    assert is_usable_adb(str(adb), lambda p: False) is False
    assert is_usable_adb(str(tmp_path / "missing" / _ADB), lambda p: True) is False


def test_is_usable_adb_rejects_when_validator_raises(tmp_path: Path) -> None:
    adb = _make(tmp_path / _ADB)

    def broken(_: str) -> bool:
        raise RuntimeError("boom")

    assert is_usable_adb(str(adb), broken) is False


def test_version_validator_is_a_callable_factory() -> None:
    assert callable(version_validator())
    assert callable(version_validator(timeout=3.0))