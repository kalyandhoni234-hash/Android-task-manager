"""Dependency-policy guard: pinned Windows release toolchain + same-venv audit.

Static, dependency-free checks (regex over text; no exact line numbers or
whitespace assumptions) encoding the Priority #2 hardening decisions:

* the Windows EXE dependency subset is exactly pinned via
  ``packaging/windows-build-constraints.txt``;
* ``packaging/build_windows.ps1`` provisions, audits and freezes through ONE
  interpreter (``$Py``): INSTALL -> AUDIT SAME VENV -> BUILD EXE;
* pip-audit runs inside that build venv before the first PyInstaller
  invocation, and any finding fails the build;
* a provenance snapshot (``dist/BUILD_ENV_FREEZE.txt``) is produced from the
  same interpreter before packaging;
* CI's GUI installs consume the same constraints file;
* runtime dependencies stay empty unless deliberately ``==``-pinned.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "packaging" / "windows-build-constraints.txt"
BUILD_SCRIPT = ROOT / "packaging" / "build_windows.ps1"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = ROOT / "pyproject.toml"

#: Packages that MUST be covered by an exact pin (normalized names).
_REQUIRED_PINS = {"pyside6", "shiboken6", "pyinstaller"}

_PIN_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s#]+)\s*$")


def _constraints_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN_LINE.match(line)
        assert match is not None, f"constraints line is not an exact pin: {raw!r}"
        entries[match.group(1).lower().replace("_", "-")] = match.group(2)
    return entries


def _script_text() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8")


def _first_pyinstaller_index(text: str) -> int:
    index = text.find("-m PyInstaller")
    assert index != -1, "build script never invokes PyInstaller"
    return index


# --------------------------------------------------------------------------
# A-C. Constraints file: exists, non-empty, exact pins, required coverage
# --------------------------------------------------------------------------

def test_constraints_file_exists_and_is_non_empty():
    assert CONSTRAINTS.is_file(), f"{CONSTRAINTS.name} missing"
    entries = _constraints_entries()
    assert len(entries) >= 1, "constraints file must pin at least one package"


def test_constraints_use_exact_version_pins_only():
    # _constraints_entries() already asserts every content line matches
    # name==version; this test makes the intent explicit and fails loudly.
    for raw in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert re.match(r"^[A-Za-z0-9._-]+==[^\s]+$", stripped), (
            f"non-exact constraint entry: {raw!r}"
        )


def test_constraints_cover_exe_affecting_packages():
    names = set(_constraints_entries())
    missing = _REQUIRED_PINS - names
    assert not missing, f"constraints missing required pins: {sorted(missing)}"


# --------------------------------------------------------------------------
# D-G. Build script: constrained provisioning + same-venv audit ordering
# --------------------------------------------------------------------------

def test_build_script_references_constraints_file():
    assert "windows-build-constraints.txt" in _script_text()


def test_build_script_installs_constrained_gui_extra():
    text = _script_text()
    gui_install = [
        line for line in text.splitlines()
        if "pip" in line and '".[gui]"' in line
    ]
    assert gui_install, "GUI extra install not found in build script"
    for line in gui_install:
        assert "-c $Constraints" in line, (
            f"GUI install is not constrained: {line.strip()!r}"
        )


def test_every_pip_call_uses_the_same_build_interpreter():
    for line in _script_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # prose may mention pip; only invocations matter
        if "pip install" in line or "pip freeze" in line or "pip_audit" in line:
            assert "$Py" in line, (
                f"pip invocation outside the build venv interpreter: {line.strip()!r}"
            )


def test_pip_audit_runs_in_build_venv_before_first_pyinstaller_call():
    text = _script_text()
    audit = text.find("-m pip_audit")
    assert audit != -1, "build script must run pip-audit"
    assert audit < _first_pyinstaller_index(text), (
        "pip-audit must run before the first PyInstaller invocation"
    )
    # A vulnerability must fail the build: the exit code is checked.
    tail = text[audit:]
    exit_check = re.search(r"\$LASTEXITCODE\s+-ne\s+0", tail[:600])
    assert exit_check is not None, "pip-audit failures must abort the build"


def test_no_second_unconstrained_pyinstaller_install_path():
    text = _script_text()
    installer_lines = [
        line for line in text.splitlines()
        if "pip install" in line and "pyinstaller" in line.lower()
    ]
    assert len(installer_lines) == 1, (
        f"expected exactly one PyInstaller install path, got {len(installer_lines)}"
    )
    assert "-c $Constraints" in installer_lines[0], (
        "PyInstaller install must be constrained"
    )
    # The old independent range authority is gone.
    assert '"pyinstaller>=6.0"' not in text


# --------------------------------------------------------------------------
# H. CI consumes the same constraints for GUI installs
# --------------------------------------------------------------------------

def test_ci_gui_installs_reference_constraints_file():
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    gui_lines = [
        line for line in text.splitlines()
        if '".[dev,gui]"' in line and "pip install" in line
    ]
    assert gui_lines, "no .[dev,gui] install found in ci.yml"
    for line in gui_lines:
        assert "windows-build-constraints.txt" in line, (
            f"CI GUI install does not use the constraints file: {line.strip()!r}"
        )


# --------------------------------------------------------------------------
# I. Runtime dependencies stay empty (or explicitly pinned)
# --------------------------------------------------------------------------

def test_runtime_dependencies_empty_or_fully_pinned():
    text = PYPROJECT.read_text(encoding="utf-8")
    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.MULTILINE)
    assert block is not None, "pyproject [project] dependencies array not found"
    body = block.group(1).strip()
    if not body:
        return  # intentionally zero runtime dependencies
    for entry in body.split(","):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        assert "==" in entry, (
            f"floating runtime dependency introduced: {entry!r}"
        )


# --------------------------------------------------------------------------
# J. Provenance snapshot from the same interpreter, before packaging
# --------------------------------------------------------------------------

def test_provenance_freeze_uses_same_interpreter_before_packaging():
    text = _script_text()
    freeze = text.find("-m pip freeze")
    assert freeze != -1, "build script must capture a pip-freeze provenance snapshot"
    assert "BUILD_ENV_FREEZE.txt" in text, "provenance artifact name missing"
    assert freeze < _first_pyinstaller_index(text), (
        "provenance must be captured before PyInstaller packages the EXE"
    )
