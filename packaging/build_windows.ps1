# Builds the standalone Windows executables with PyInstaller.
#
# Produces:
#   dist\AndroidTaskManager.exe        — windowed build for normal users
#   dist\AndroidTaskManager-debug.exe  — console build that echoes connection
#                                        state (diagnostics)
#   dist\BUILD_ENV_FREEZE.txt          — pip freeze of the exact build venv
#                                        (provenance, published with the
#                                        release alongside SHA256SUMS.txt)
#
# Dependency policy: everything that gets frozen into the EXE is pinned via
# packaging\windows-build-constraints.txt, and the build venv is audited in
# place (INSTALL -> AUDIT SAME VENV -> BUILD) before PyInstaller runs.
#
# Both builds carry the product icon (packaging\assets\atm.ico) and a Windows
# version resource generated from the single version authority
# (src\android_task_manager\__init__.py, via packaging\make_version_file.py).
# ADB is deliberately NOT bundled - see README "Why is ADB not bundled?".
#
# The build uses its own clean virtual environment (.venv-build), so the
# developer's Python stays untouched. Run from the repository root:
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Prerequisite: a Python 3.10+ installation on the PATH.

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Venv = Join-Path $Root ".venv-build"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    Write-Host "Creating build venv at $Venv ..."
    python -m venv $Venv
}

$Py = Join-Path $Venv "Scripts\python.exe"

# Single version authority for everything frozen into the EXE (Qt/PySide6
# family + PyInstaller and its hook pack). The constraints file is resolved
# once per release cycle; pip-audit below validates this exact environment
# before anything is packaged.
$Constraints = Join-Path $Root "packaging\windows-build-constraints.txt"

Write-Host "Installing the app with the GUI extra (constrained) ..."
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet -c $Constraints ".[gui]"

Write-Host "Installing PyInstaller (constrained) ..."
& $Py -m pip install --quiet -c $Constraints "pyinstaller"

# INSTALL -> AUDIT SAME VENV -> BUILD EXE.
# pip-audit runs through the same interpreter ($Py) against the environment
# that is about to be frozen into the executables. Any reported vulnerability
# fails here instead of shipping inside a release artifact. pip-audit itself
# is an auditor (never bundled into the EXE), so its own version floats.
Write-Host "Installing pip-audit into the build venv ..."
& $Py -m pip install --quiet "pip-audit>=2.9"

Write-Host "Auditing Windows build dependencies (same venv as the EXE) ..."
& $Py -m pip_audit
if ($LASTEXITCODE -ne 0) {
    throw "pip-audit reported vulnerabilities in the Windows build environment."
}

# Provenance: record the dependency set of THIS interpreter next to the
# release artifacts, before packaging begins. Contains package==version
# lines only - never secrets or host details beyond package versions.
Write-Host "Recording build-environment provenance (dist\BUILD_ENV_FREEZE.txt) ..."
New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist") | Out-Null
& $Py -m pip freeze | Set-Content -Path (Join-Path $Root "dist\BUILD_ENV_FREEZE.txt")

# The package version is the single source of truth - read it back so the
# Windows version resource and the final output messages match it exactly.
$Version = & $Py -c "from android_task_manager import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
    throw "Could not read the package version"
}

Write-Host "Generating the Windows version resource (v$Version) ..."
& $Py packaging\make_version_file.py
if ($LASTEXITCODE -ne 0) { throw "Version resource generation failed" }

$VersionFile = Join-Path $Root "packaging\build\version_info.txt"
$Icon = Join-Path $Root "packaging\assets\atm.ico"
$CommonArgs = @(
    "--noconfirm", "--clean", "--onefile",
    "--version-file", $VersionFile,
    "--icon", $Icon
)

Write-Host "Building AndroidTaskManager.exe (windowed) ..."
& $Py -m PyInstaller @CommonArgs --windowed --name AndroidTaskManager packaging\entry_gui.py
if ($LASTEXITCODE -ne 0) { throw "Windowed build failed" }

Write-Host "Building AndroidTaskManager-debug.exe (console) ..."
& $Py -m PyInstaller @CommonArgs --console --name AndroidTaskManager-debug packaging\entry_console.py
if ($LASTEXITCODE -ne 0) { throw "Console build failed" }

$Gui = Join-Path $Root "dist\AndroidTaskManager.exe"
$Debug = Join-Path $Root "dist\AndroidTaskManager-debug.exe"
$GuiHash = (Get-FileHash $Gui -Algorithm SHA256).Hash.ToLowerInvariant()
$DebugHash = (Get-FileHash $Debug -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host ""
Write-Host "Done (v$Version):"
Write-Host "  $Gui  ($([math]::Round((Get-Item $Gui).Length / 1MB, 1)) MB)"
Write-Host "    SHA-256: $GuiHash"
Write-Host "  $Debug  ($([math]::Round((Get-Item $Debug).Length / 1MB, 1)) MB)"
Write-Host "    SHA-256: $DebugHash"