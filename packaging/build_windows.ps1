# Builds the standalone Windows executables with PyInstaller.
#
# Produces:
#   dist\AndroidTaskManager.exe        — windowed build for normal users
#   dist\AndroidTaskManager-debug.exe  — console build that echoes connection
#                                        state (diagnostics)
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

Write-Host "Installing the app with the GUI extra ..."
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet ".[gui]"

Write-Host "Installing PyInstaller ..."
& $Py -m pip install --quiet "pyinstaller>=6.0"

Write-Host "Building AndroidTaskManager.exe (windowed) ..."
& $Py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name AndroidTaskManager packaging\entry_gui.py
if ($LASTEXITCODE -ne 0) { throw "Windowed build failed" }

Write-Host "Building AndroidTaskManager-debug.exe (console) ..."
& $Py -m PyInstaller --noconfirm --clean --onefile --console `
    --name AndroidTaskManager-debug packaging\entry_console.py
if ($LASTEXITCODE -ne 0) { throw "Console build failed" }

$Gui = Join-Path $Root "dist\AndroidTaskManager.exe"
$Debug = Join-Path $Root "dist\AndroidTaskManager-debug.exe"
Write-Host ""
Write-Host "Done:"
Write-Host "  $Gui  ($([math]::Round((Get-Item $Gui).Length / 1MB, 1)) MB)"
Write-Host "  $Debug  ($([math]::Round((Get-Item $Debug).Length / 1MB, 1)) MB)"