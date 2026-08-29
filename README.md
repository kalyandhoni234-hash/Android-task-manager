<div align="center">

# Android Task Manager

**A powerful desktop Android monitoring, diagnostics, and management tool built around ADB.**

[![v1.0.0](https://img.shields.io/badge/version-1.0.0-0078D6?style=flat-square)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/tag/v1.0.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![ADB](https://img.shields.io/badge/ADB-Android-3DDC84?style=flat-square&logo=android&logoColor=white)](https://developer.android.com/tools/adb)
[![CI](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-2267%20passing-7C3AED?style=flat-square)](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kalyandhoni234-hash/Android-task-manager?style=flat-square&label=release)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

**Android Task Manager** is a PC-side desktop application that talks to an Android device over **ADB** and renders live system telemetry — CPU, memory, processes, battery, network and storage — together with an evidence-based **Diagnostics** engine, an **Applications** manager, and an **AI Copilot** assistant (Gemini) that helps you understand what you are seeing. It runs as a dependency-light terminal dashboard or as a full PySide6 desktop GUI.

[![Download for Windows](https://img.shields.io/badge/Download-AndroidTaskManager.exe-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v1.0.0/AndroidTaskManager.exe)
[![Product website](https://img.shields.io/badge/Product-Website-white?style=for-the-badge&logo=github&logoColor=white)](https://kalyandhoni234-hash.github.io/Android-task-manager/)
[![Releases](https://img.shields.io/badge/GitHub-Releases-white?style=for-the-badge&logo=github&logoColor=white)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases)

</div>

---

## Product Overview

Android Task Manager turns *your* PC into a window into *your* Android device. The device never needs to install anything: the app reaches it through `adb shell` and reads standard Linux/Android interfaces — `/proc`, `/sys/devices`, `dumpsys` and `pm` — parses the raw output, and normalizes it into typed models that the terminal and the GUI render.

It is built for people who are tired of switching between `adb` commands and scattered terminal output: engineers, power users, support staff and the simply curious who want a single, readable view of what an Android device is actually doing. Monitoring and inspection are **read-only**; the only interactive operations are a small set of explicit, package-verified device actions, each of which requires a selection and (for destructive actions) an explicit confirmation naming the exact target package.

Two ways to use it:

- **Terminal mode** — a dependency-light interactive dashboard (CPU / memory / processes / battery / network) with per-reader sampling cadences you control.
- **Desktop GUI (PySide6)** — a live dashboard with history graphs, a selectable process table, an on-demand **Process Inspector** (`/proc/<pid>`), a per-process **Network Connections** investigation (socket tables), a **Diagnostics** page (evidence-based device health findings), a per-device **Baseline persistence** store, an **exportable device report**, an **Applications manager** (installed-app inventory with per-package details and capability-gated device actions), an **AI Copilot** assistant, and a **Settings** page with a four-theme switcher.

## Feature Highlights

### Device Monitoring

- **CPU** — aggregate utilization from `/proc/stat` *deltas* between two samples (never a single snapshot), per-core utilization, and per-core frequency from `scaling_cur_freq` sysfs nodes. First sample reports `N/A` (a delta has no baseline yet).
- **Memory** — `MemAvailable` as the primary pressure indicator (not `MemFree`: cache is reclaimable), used-share, and Total / Available / Free / Cached / Buffers breakdown. Values normalized to KiB.
- **Battery** — level (`level / scale`), charging status and health (Android enum numbers normalized to human-readable states), voltage, temperature (0.1 °C → °C), technology and power source.
- **Network** — download/upload throughput from `/proc/net/dev` *deltas* (bytes per second), interface classification (Wi-Fi / Mobile Data / VPN / …) by a documented heuristic, and interface filtering (active-only by default with a *show all* toggle).
- **Storage** — live used-share of the internal `/data` volume, re-read on its own slow cadence (default 30 s) and classified against the same canonical thresholds as the other metrics.
- **Processes** — live process table (PID, UID, CPU%, MEM%, State, Name), default-sorted by CPU usage, with name filtering and CPU/memory sorting. Identity comes from `ps -A -o PID,UID,NAME`; dynamic metrics come from `top -n 1` and are merged **by PID** — never by name.
- **Device information** — an "About phone" style dashboard: device summary, hardware (manufacturer/brand/model/board/SoC, CPU, cores, max frequency), Android/software (version, API level, security patch, build, kernel, baseband), memory, battery, storage (internal `/data` volume with usage bar), display (resolution, density, refresh rate) and identifiers. Static facts are collected **once per connection session**; live battery/memory/CPU reuse the existing collectors' snapshots.

### Diagnostics & Health

- A deterministic, rule-based **Diagnostics** engine over the already-collected snapshots — CPU, memory, battery, storage and security facts — turning thresholds into structured findings, each with **WHAT / WHY / EVIDENCE / RECOMMENDED ACTION**.
- Findings are **individual and explainable, never a score**: three explicit severity levels (INFO / WARNING / CRITICAL); `UNKNOWN` data produces no claim, and the rules treat "no evidence" as "no finding".
- The **Diagnostics page** renders findings severity-first; an *absence* of findings is shown honestly as "no issues detected" — not as proof of health.
- A deterministic **device-health** view scores the current snapshots into a 0–100 overall score and per-component statuses (CPU, memory, battery, storage, processes, applications, connectivity) with typed findings. Missing data contributes no score and no finding.

### Applications

- The **Applications page** (sidebar → MANAGE → Applications) lists installed apps: package, type (SYSTEM / USER), enabled state, UID, version code and APK path, with client-side filtering and numeric-aware column sorting; system rows are tinted so the destructive-control boundary reads at a glance.
- Inventory is normalized from `pm list packages -f -U --show-versioncode` plus the system/user/disabled sets — one typed `ApplicationSnapshot`, with an honest empty state on failure, and a full refresh whenever the device (re)connects or a state-changing action succeeds.
- Selecting a row reads **per-package details** on demand (`dumpsys package`): version name/code, UID, APK path, installer, enabled state, launch activity and component counts.
- The details panel carries the capability-gated action row (Open / Info / Force Stop / Disable|Enable / Uninstall) and an **Audit Permissions** button. The Process Inspector's **Manage** button jumps from a verified process to its application row.

### AI Copilot (Gemini)

An in-app assistant that helps you **understand your device, diagnose problems and explain what you are seeing** — it is advisory, not autonomous. It is powered by Google's **Gemini** API and uses the live device context (CPU, memory, processes, current page and diagnostics findings) plus the conversation history to ground its answers.

- Open the **AI Copilot** page (sidebar → AI) and ask plain questions: *"Why is my phone slow?"*, *"What's using my RAM?"*, *"Why is my battery draining?"*, *"Explain my health"*. Built-in quick prompts get you started.
- The key is **yours**: you provide a Gemini API key, it is stored locally on your computer (`copilot-config.json` in the user-data directory), and it is never sent anywhere except to the Gemini API. A **Test Connection** button validates the key before you rely on it.
- Responses are returned with follow-up suggestions; provider errors (bad key, rate limit, model not found, timeout, offline) are mapped to clear, non-technical messages — the app never crashes on a Copilot failure.
- The Copilot runs on a background worker thread; the dashboard keeps sampling while a request is in flight.

### Themes

Four built-in themes, switchable from **Settings** (sidebar → SYSTEM → Settings):

- **Dark** — the default desktop look.
- **Light** — a high-contrast light theme.
- **System** — follows the OS light/dark preference.
- **Cyber** — a neon-accented theme for the dashboard.

Theme selection is persistent and applied across every page.

### Safety by design

- **Read-only by construction.** The app only reads `/proc`, `/sys` and `dumpsys`/`pm` state. No process is started, stopped, killed, or re-prioritized except the explicit, selected, package-verified device actions.
- **No arbitrary ADB shell.** Every command is a fixed argument list; the tool never forwards interactive or free-form shell input.
- **Verified package identity.** No device action runs without the target being positively verified against the device's installed-package list.
- **Capability-gated destructive controls.** System applications never receive uninstall/disable requests — the gate is enforced in the widget and re-checked at the window before dispatch.
- **No fabricated data.** A value that cannot be read is reported as `N/A` — never an invented zero.
- **Single source of truth:** `src/android_task_manager/__init__.py` (`__version__`) drives the package version, the Windows EXE version resource and the release tag.

## Screenshots

![Android Task Manager dashboard](android-task-manager-website/website/public/screenshots/dashboard.png)

*The GUI dashboard on a connected device — process table, inspector, network and monitoring widgets (Dark theme). The dashboard screenshot is a real capture from the application; the latest interface screenshots are also on the [product website](https://kalyandhoni234-hash.github.io/Android-task-manager/).*

## How It Works

```
Android Device (USB / Wi-Fi)
        │
        │ adb shell  (read-only: cat /proc/..., cat /sys/..., dumpsys, pm)
        ▼
  ConnectionManager            (adb/connection.py — the ONLY subprocess import)
        │
        ├── CPU Collector        ── /proc/stat deltas + sysfs frequencies
        ├── Memory Collector     ── /proc/meminfo
        ├── Process Collector     ── ps -A identity + top -n 1 metrics, merged by PID
        ├── Battery Collector     ── dumpsys battery
        ├── Network Collector     ── /proc/net/dev deltas
        └── Investigation Col.    ── /proc/net/{tcp,tcp6,udp,udp6} + pm list packages -U
                │
                ▼
       Normalized Models        (frozen dataclasses — pure, validated)
                │
         ┌──────┴──────────┬────────────┐
         ▼                 ▼            ▼
   Terminal         GUI (PySide6)    AI Copilot
  renderer      MonitorWorker · InspectorWorker · ActionWorker ·
                AppsWorker · CopilotWorker (background threads — the
                dashboard never blocks)
```

The key architectural rule: **collectors never invoke `subprocess` directly.** All ADB execution is centralized in `adb/connection.py` (`ConnectionManager`, which satisfies the `CommandRunner` protocol that every collector and GUI worker consumes). Raw device output is parsed into normalized, frozen-dataclass models, and only those models reach the renderers — neither the terminal renderer nor the GUI widgets ever touch ADB or parse device text.

## Technology Stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Language | Python ≥ 3.10 | core app uses only the standard library |
| Desktop GUI | PySide6 ≥ 6.5 (Qt for Python) | optional extra, `pip install ".[gui]"` |
| Device bridge | ADB (`adb shell`) | not bundled (see [Why is ADB not bundled?](#why-is-adb-not-bundled)) |
| AI assistant | Gemini API | user-provided key, stored locally; optional |
| Term renderer | custom, dependency-light | `terminal/renderer.py` |
| Windows packaging | PyInstaller ≥ 6 | one-file windowed + debug builds |
| Tests | pytest ≥ 7 | fixture-driven, GUI headless |
| Lint / types | Ruff, mypy | enforced in CI |
| CI/CD | GitHub Actions | Linux matrix (3.10–3.12) + Windows release build |
| Product site | Next.js (static export) | hosted on GitHub Pages |

## Installation

### Windows — EXE

No Python required:

1. Download **`AndroidTaskManager.exe`** (a self-contained PySide6 build) from the [v1.0.0 release](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v1.0.0/AndroidTaskManager.exe) — or from the [product website](https://kalyandhoni234-hash.github.io/Android-task-manager/), which links directly to the exact published artifact and shows its SHA-256 checksum.
2. Double-click the EXE. You do **not** need Python, git or the source tree.
3. The **connection-setup screen** walks you through the only remaining requirement — ADB + a connected device (details below).

The EXE carries the product icon and a Windows version resource (product version = release version, from the single version source). On first launch, Windows SmartScreen may warn about an unsigned executable — it is a portable build that only talks to your device over ADB; choose *More info → Run anyway* if you trust the source. The v1.0.0 production EXE SHA-256 is:

```
C94F4090AEECC71920C63CEDA30618FB43CF04A2E59364B17AC48B70859999D1
```

### From Source

Prerequisites: Python ≥ 3.10 and git. For the GUI, an Android device helps, but the test suite needs none.

```bash
git clone https://github.com/kalyandhoni234-hash/Android-task-manager.git
cd android-task-manager

python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[dev,gui]"
```

Run the terminal version:

```bash
android-task-manager --help
android-task-manager
android-task-manager --adb "C:\platform-tools\adb.exe"
```

Run the GUI:

```bash
android-task-manager-gui
```

The GUI accepts the same `--adb`, `--device`, `--interval`, `--process-interval`, `--battery-interval`, `--memory-interval`, `--network-interval`, `--network-investigation-interval`, `--storage-interval` and `--timeout` flags; it has no `--samples` flag.

## Android & ADB Setup

**Why ADB?** Android exposes its system state through `adb shell` against standard interfaces; Android Task Manager is a viewer over that channel. It does not root the device and does not install anything on it.

1. **Enable Developer Options** on the device: *Settings → About phone* → tap *Build number* seven times.
2. **Enable USB debugging**: *Settings → System → Developer options* → turn on **USB debugging**.
3. **Install Android Platform Tools** on your PC: download the official build from the [Android developer site](https://developer.android.com/tools/releases/platform-tools) and unzip it, e.g. to `C:\platform-tools` (contains `adb.exe`). ADB does **not** need to be on `PATH` — the app can find it.
4. **Connect the device** with a USB cable; on the device, accept *"Allow USB debugging?"* and tick *Always allow from this computer*.
5. **Verify** (any terminal):
    ```bat
    C:\platform-tools\adb.exe devices
    ```
    The serial must appear as `device` (not `unauthorized` or `offline`).
6. Launch **AndroidTaskManager.exe**. It locates `adb`, connects, and shows the dashboard.
7. For **adb over Wi-Fi**: connect the phone and PC to the same network, then `adb pair` / `adb connect <ip>:5555`; the app treats it like any ADB connection.

### ADB discovery

The app finds `adb` without you touching your `PATH`, in this priority order:

1. The explicit path you passed (`--adb`, or *Locate ADB* in the GUI) — verified with `adb version` before use.
2. An `adb.exe` placed next to the app itself (distribution-local copy).
3. `adb` on `PATH`.
4. Well-known SDK locations, detected safely (only when the file actually exists): `%ANDROID_HOME%/platform-tools`, `%ANDROID_SDK_ROOT%/platform-tools`, `%LOCALAPPDATA%\Android\Sdk\platform-tools`, `%USERPROFILE%\AppData\Local\Android\Sdk\platform-tools`.

Every candidate is confirmed with `adb version` before it is accepted; a file that exists but cannot launch is skipped in favor of the next candidate; duplicate paths are tried only once.

### Why is ADB not bundled?

The official `adb.exe` binaries are distributed under the [Android SDK License Agreement](https://developer.android.com/tools/releases/platform-tools), whose terms restrict redistribution. The safeguard is to let you supply `adb` yourself: the app finds one you already have, or you download Platform Tools from Google and point the app at it (or drop `adb.exe` next to `AndroidTaskManager.exe`). If you compile `adb` yourself from the [AOSP source](https://android.googlesource.com/platform/packages/modules/adb/) (Apache-2.0), you are free to distribute that binary with your own build.

## AI Copilot Setup

The Copilot is optional. To enable it:

1. Open **Settings** (sidebar → SYSTEM → Settings).
2. Click **Configure API Key** (or open the **AI Copilot** page and click **Configure Gemini**).
3. Enter your **Gemini API key** and choose the model (default `gemini-2.0-flash`). Click **Test Connection** to validate it.
4. Click **Save configuration**. The key is written to `copilot-config.json` in the platform user-data directory and is never embedded in the app or uploaded anywhere except the Gemini API.
5. Open the **AI Copilot** page and ask a question.

> **Security:** Never commit your API key to Git or place it directly in source code. The key lives only in your local user-data directory (`copilot-config.json`, which is git-ignored), and the app reads it at runtime. Leaving the key field empty never overwrites an already-saved key.

## Project Structure

```
android-task-manager/
├── src/android_task_manager/
│   ├── adb/                          # ADB subprocess execution (the only subprocess import)
│   │   ├── connection.py             #   ConnectionManager — every command runs through this
│   │   └── discovery.py              #   adb.exe search order + "adb version" validation
│   ├── cpu/                          # /proc/stat parsing, delta calculation, collector
│   ├── memory/                       # /proc/meminfo parsing, collector
│   ├── battery/                      # dumpsys battery parsing (status/health enums), collector
│   ├── network/                      # /proc/net/dev parsing, delta throughput, collector
│   ├── history/                      # bounded session metric history (stats/trends/peaks)
│   ├── health/                       # device health engine (score, components, findings)
│   ├── timeline/                     # bounded event timeline (session transitions)
│   ├── rules/                        # monitoring rule engine (cooldowns, durations)
│   ├── recommend/                    # deterministic finding→recommendation mapping
│   ├── automation/                   # approval-gated, cooldown-bounded action scheduler
│   ├── process/                      # ps identity + top metrics, classification, and the
│   │                                 #   read-only /proc/<pid> inspector (inspector_* modules)
│   ├── network_investigation/        # socket tables (tcp{,6},udp{,6}) + UID attribution
│   ├── device/                       # device identity: getprop/wm/df model, parser, collector
│   ├── device_report/                # device report export: deterministic JSON artifact
│   ├── incident/                     # incident report: models · builder · renderers (JSON/HTML)
│   ├── investigation/                # investigation core: drift stability · timeline ·
│   │                                 #   attribution · why-flagged evidence · process tree
│   ├── action/                       # package verification + Open App / App Info / Force Stop /
│   │                                 #   Enable / Disable / Uninstall, capability gate
│   ├── applications/                 # application inventory: models, pm list + dumpsys parsers
│   ├── copilot/                      # AI Copilot: models, prompts, providers, service, settings
│   ├── core/                         # diagnostics: rotating local log, redaction, export
│   ├── terminal/                     # dependency-light text renderer
│   ├── gui/                          # PySide6 dashboard: sidebar, pages, widgets, workers,
│   │                                 #   copilot page/dialog/worker, styles, entry (app.py)
│   └── main.py                       # terminal entry point
├── tests/                            # pytest suite, fixture-driven (no physical device)
├── packaging/                        # build_windows.ps1, icon + version-resource assets,
│   │                                 #   entry stubs (entry_gui.py / entry_console.py)
├── docs/                             # ADRs + engineering research
├── android-task-manager-website/     # Next.js product website (static export -> out/)
├── .github/workflows/                # ci.yml · release.yml · deploy-pages.yml
├── pyproject.toml                    # single version authority (dynamic from __init__.py)
├── LICENSE                           # MIT
└── README.md
```

## Testing

```bash
python -m pytest
```

The suite: **a fixture-driven pytest suite** (`tests/`) covering the parsers (CPU, memory, process, battery, network), delta calculations, collectors, the ADB discovery/connection layers, the package-identity resolver, the application inventory, the network investigation, the incident report layer, the investigation core, device information, the device report export layer, baseline persistence, the diagnostics engine, the device-intelligence layer (history, health, timeline, rules, recommendations, automation), the Copilot integration, the GUI (widgets, sidebar navigation, pages, setup flow, actions, workers) and the reliability layer.

- **2267 tests passing** in the current baseline.
- Runs entirely against **fixed fixtures based on verified device output — no physical device required**.
- **GUI tests run headlessly** via Qt's `offscreen` platform plugin; they construct widgets, deliver snapshots, drive the monitor worker, and cover the first-run setup flow without a display.
- **Live Android-device testing is separate from CI**: USB disconnect/reconnect, authorization and long-run stability checks are performed manually on real hardware.

### Quality checks

```bash
python -m ruff check src tests        # lint (E4/E7/E9, F, I, B)
python -m mypy src/android_task_manager/core src/android_task_manager/adb \
  src/android_task_manager/device src/android_task_manager/diagnostics \
  src/android_task_manager/action src/android_task_manager/applications \
  src/android_task_manager/history src/android_task_manager/health \
  src/android_task_manager/timeline src/android_task_manager/rules \
  src/android_task_manager/recommend src/android_task_manager/automation  # type check (enforced scope)
python -m pip_audit                   # dependency vulnerability audit
```

`mypy` is scoped to the pure core + ADB layer, the device-information and diagnostics packages, and the device-intelligence packages; the rest of the GUI layer carries pre-existing PySide6 typing debt that is tracked for later phases. `pip-audit` needs the installed environment (`pip install -e ".[dev]"`).

## v1.0.0 — First Stable Release

The first stable release of Android Task Manager:

- **Stabilized monitoring and diagnostics** — delta-correct CPU/memory/network collection, honest `N/A` for unreadable values, and a deterministic, explainable Diagnostics engine.
- **Polished PySide6 GUI** — sidebar navigation, live history graphs, Process Inspector, per-process Network Investigation, Applications manager and a connection-setup screen that recovers live from every failure state.
- **Theme system** — Dark, Light, System and Cyber, persistent across pages.
- **Applications management** — installed-app inventory with per-package details, capability-gated actions (Open / Info / Force Stop / Enable / Disable / Uninstall) and permission audits.
- **Copilot / Gemini integration** — an in-app assistant that explains your device using live context, with locally stored, user-provided keys.
- **Persistent settings** — theme, baseline and Copilot configuration survive restarts.
- **Windows EXE distribution** — a portable, self-contained build (windowed + debug), published with SHA-256 checksums.
- **Regression hardening** — 2267 automated tests, Ruff, mypy and a dependency audit enforced in CI.
- **Production validation** — built and versioned `1.0.0`, with manual visual acceptance on Windows.

It is a stable release, not a beta or preview.

## Roadmap

**Current (shipped in v1.0.0):** the features described above — monitoring, diagnostics, applications management, AI Copilot, themes, persistent settings and the Windows EXE.

**Possible future directions (not yet implemented — listed as ideas, not promises):**
- Additional ADB-free data sources and richer device reports.
- More Copilot prompt surfaces and offline/self-hosted model providers.
- Localization and accessibility passes.
- Signed Windows builds.

## Contributing

1. Fork the repository and create a feature branch.
2. Install development dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # or: source .venv/bin/activate
   pip install -e ".[dev,gui]"
   ```
3. Make your change. Keep the architecture intact: collectors stay read-only and go through `ConnectionManager`; new device actions must be package-verified and capability-gated.
4. Run the checks:
   ```bash
   python -m pytest
   python -m ruff check src tests
   python -m mypy src/android_task_manager/core src/android_task_manager/adb \
     src/android_task_manager/device src/android_task_manager/diagnostics \
     src/android_task_manager/action src/android_task_manager/applications \
     src/android_task_manager/history src/android_task_manager/health \
     src/android_task_manager/timeline src/android_task_manager/rules \
     src/android_task_manager/recommend src/android_task_manager/automation
   ```
5. Submit a pull request describing the change and the evidence (tests/logs) behind it.

## License & Credits

- **License:** MIT — see [LICENSE](LICENSE).
- **Qt / PySide6** — the desktop GUI is built on Qt for Python (PySide6), licensed under the LGPL.
- **ADB** — device connectivity uses the Android Debug Bridge; `adb` binaries are not redistributed (see [Why is ADB not bundled?](#why-is-adb-not-bundled)).
- **Gemini** — the optional AI Copilot uses Google's Gemini API; you supply your own key.
- **PyInstaller** — packages the standalone Windows executable.
- **Next.js** — powers the product website (static export).
- **pytest / Ruff / mypy / GitHub Actions** — testing, linting, type-checking and CI.

No telemetry is collected by the application; local diagnostic logs are written only to your machine and never uploaded.
