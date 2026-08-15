<div align="center">

# Android Task Manager

**A live Android/Linux system monitor for your PC — CPU, memory, processes, battery and network, pulled from a connected Android device over ADB.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![GUI](https://img.shields.io/badge/GUI-PySide6-41CD52?style=flat-square&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![ADB](https://img.shields.io/badge/ADB-Android-3DDC84?style=flat-square&logo=android&logoColor=white)](https://developer.android.com/tools/adb)
[![CI](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/kalyandhoni234-hash/Android-task-manager?style=flat-square&label=release)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

**Android Task Manager** is a PC-side monitoring tool that talks to an Android device over **ADB** and renders live system telemetry — CPU (aggregate, per-core, per-core frequency), memory pressure (`MemAvailable`), process tables with per-process metrics, battery state, and network throughput — either as a lightweight **terminal dashboard** or as a full **PySide6 desktop GUI**.

**Get it — no Python required:**

[![Download for Windows](https://img.shields.io/badge/Download-AndroidTaskManager.exe-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v0.2.0/AndroidTaskManager.exe)
[![Product website](https://img.shields.io/badge/Product-Website-white?style=for-the-badge&logo=github&logoColor=white)](https://kalyandhoni234-hash.github.io/Android-task-manager/)
[![Releases](https://img.shields.io/badge/GitHub-Releases-white?style=for-the-badge&logo=github&logoColor=white)](https://github.com/kalyandhoni234-hash/Android-task-manager/releases)

</div>

---

## Overview

Android Task Manager turns *your* PC into a window into *your* Android device. The device is never required to install anything: the app reaches it through `adb shell` and reads standard Linux/Android interfaces — `/proc`, `/sys/devices`, `dumpsys` and `pm` — parses the raw output, and normalizes it into typed models that the terminal and the GUI render.

Two ways to use it:

- **Terminal mode** — a dependency-light interactive dashboard (CPU / memory / processes / battery / network) with per-reader sampling cadences you control.
- **Desktop GUI (PySide6)** — a live dashboard with history graphs, a selectable process table, an on-demand **Process Inspector** (`/proc/<pid>`), a per-process **Network Connections** investigation (socket tables), and three explicit, package-verified device actions: **Open App**, **App Info**, **Force Stop**.

Monitoring is **read-only**. The tool never writes to the device; the three device actions are the only interactive operations, each requires an explicit selection, and each runs only against a package whose identity has been verified against the device's installed-package list.

## ✨ Features

### 📊 System Monitoring

- **CPU** — aggregate utilization from `/proc/stat` *deltas* between two samples (never a single snapshot), per-core utilization, and per-core frequency from `scaling_cur_freq` sysfs nodes. First sample reports `N/A` (a delta has no baseline yet).
- **Memory** — `MemAvailable` as the primary pressure indicator (not `MemFree`: cache is reclaimable), used-share, and Total / Available / Free / Cached / Buffers breakdown. Values normalized to KiB.
- **Battery** — level (`level / scale`), charging status and health (Android enum numbers normalized to human-readable states), voltage, temperature (0.1 °C → °C), technology and power source.
- **Network** — download/upload throughput from `/proc/net/dev` *deltas* (bytes per second), interface classification (Wi-Fi / Mobile Data / VPN / …) by a documented heuristic, and interface filtering (active-only by default with a *show all* toggle).
- **History graphs** (GUI) — bounded live windows for CPU, memory, network and battery so you can see recent trends, not just the current value.

### 🔎 Process Monitoring & Inspector

- Live process table (GUI): **PID, CPU%, MEM%, State, Name**, default-sorted by CPU usage, with name filtering and sorting of CPU/memory.
- Process classification — a documented heuristic: bracketed names (`[kworker/0:1]`) → kernel thread; `uid < 10000` → system; otherwise → user/app. The monitor's own helper process is hidden from the table.
- Identity comes from `ps -A -o PID,UID,NAME` (authoritative); dynamic metrics come from `top -n 1` and are merged **by PID** — never by name or row order. `%CPU` above 100 is kept as-is (multi-core), not clamped.
- **Process Inspector** (GUI) — on-demand, read-once inspection of a selected process:
  - `/proc/<pid>/status` → Name, State, UID, Threads, Virtual (`VmSize`), Resident (`VmRSS`), Shared (`RssShmem`).
  - `/proc/<pid>/stat` → priority, nice, thread count (used as fallbacks; parsed around the `comm` group so names with spaces/parentheses are safe).
  - `/proc/<pid>/cmdline` → NUL-separated argv, space-joined; empty → `N/A`, nothing invented.
  - `/proc/<pid>/io` → optional `read_bytes`/`write_bytes`; when the file is permission-protected, both stay `N/A` — never a fabricated zero.
  - If the process exits mid-inspection, the panel shows a clean *"Process no longer available"* state instead of crashing.
  - Inspections run on a **background worker thread**; the dashboard keeps sampling while a read is in flight.

### 🔍 Process Search & Sorting

- Sort the process table by **CPU** or **memory** (highest first) and **filter** by name — the table re-renders from the latest snapshot without touching the device.

### ⚡ Device Actions *(GUI, explicit, package-verified)*

- **Open App** — resolved to a verified launch component and started with `am start -W -n`.
- **App Info** — opens the Android settings page for the package (via `am start` targeting the app-details intent).
- **Force Stop** — `am force-stop <package>`.
- **Identity is never guessed.** Every action is resolved through the `PackageResolver`: an in-memory, reconnect-refreshed view of the device's installed packages (`pm list packages`). A process without a positive verification against the installed list has **no** application identity — nothing is acted on, and a rejected candidate (e.g. a shell module, a non-app module process, a secondary-process suffix) is rejected up front.
- Deliberately **no** kill-all, no cache/data clearing, no restarts — no write access of any other kind.

### 🌐 Network Monitoring

- Delta-based download/upload throughput; traffic aggregated per interface and grouped by type over the active connection.
- Interface classification (Wi-Fi / Mobile Data / VPN / Loopback / Other) is a documented heuristic over interface names — honest about what it infers.
- GUI default shows only active interfaces; *Show all interfaces* reveals idle, loopback and virtual ones.

### 🔬 Per-Process Network Investigation *(GUI)*

- The Inspector's **Network Connections** table reads the device's four socket tables — `/proc/net/tcp`, `tcp6`, `udp`, `udp6` — on a slow cadence (default 10 s) and shows local/remote endpoints and connection states.
- Sockets are attributed to the selected process **by its UID**, resolved against the exact packages sharing that UID (`pm list packages -U`). This is deliberately **not** PID-level attribution: Android exposes no per-socket PID to a non-root process, so the tool says that instead of guessing. See `docs/m14-network-research.md` for the research behind this.
- Each table is read independently: a permission failure on one table never hides the sockets visible in the others, and each readable-source state is reported. When the device refuses the socket reads entirely, the section explains that rather than fabricating data.

### 📋 Automated Incident Reporting *(GUI)*

- **Generate Report** — one click aggregates the session into a deterministic, evidence-backed investigation artifact: findings (drift events, heuristic signals, permission combination flags), evidence rows (processes, sockets, packages, permission audits), a chronological timeline, severity counts and an overall assessment (`REVIEW REQUIRED` / `REVIEW RECOMMENDED` / `INFORMATIONAL` / `NO SIGNIFICANT FINDINGS`).
- **Export JSON / HTML / PDF** — the same self-contained HTML feeds the viewer dialog and the PDF writer; JSON is canonical and deterministic. Every export writes off the GUI thread and always reports back.
- **An investigation artifact, never a verdict.** The report preserves the existing analysis layers' own wording, never concludes "malware"/"compromised", and recommends *investigation steps only* — no uninstall/disable/kill/delete. Unavailable data renders as "Unavailable", never a fabricated zero; every timeline entry carries a real timestamp.
- **Evidence integrity** — every report carries a SHA-256 of its canonical payload (stdlib `hashlib`, no cryptography dependency) to detect accidental change.
- See `docs/adr-0001-incident-reporting.md` for the design decisions (no LLM, read-only by construction, severity semantics, PDF placement).

### 🔌 ADB & Device Handling

- Automatic **ADB discovery** (see [ADB discovery](#-adb-discovery)) with `adb version` validation of every candidate.
- A **connection-setup screen** (GUI) that guides through every failure state — ADB not found, no device, not authorized, offline, multiple devices — **auto-retries** every couple of seconds and recovers live (plugging in, authorizing or locating adb mid-session works without restart).
- Explicit device selection for multi-device setups (`--device` / device picker).
- Every ADB command runs through one `ConnectionManager` with a per-command timeout and clean, typed error states.

## 🖥️ Screenshots

![Android Task Manager dashboard](android-task-manager-website/website/public/screenshots/dashboard.png)

*The GUI dashboard on a connected device — process table, inspector, network and monitoring widgets. The dashboard screenshot is captured from the real application; the latest interface screenshots are also on the [product website](https://kalyandhoni234-hash.github.io/Android-task-manager/).*

## 🏗 How It Works

```
Android Device (USB)
       │
       │ adb shell  (read-only: cat /proc/..., cat /sys/..., dumpsys, pm)
       ▼
 ConnectionManager            (adb/connection.py — the ONLY subprocess import)
       │
       ├── CPU Collector        ── /proc/stat deltas + sysfs frequencies
       ├── Memory Collector     ── /proc/meminfo
       ├── Process Collector    ── ps -A identity + top -n 1 metrics, merged by PID
       ├── Battery Collector    ── dumpsys battery
       ├── Network Collector    ── /proc/net/dev deltas
       └── Investigation Col.   ── /proc/net/{tcp,tcp6,udp,udp6} + pm list packages -U
               │
               ▼
      Normalized Models        (frozen dataclasses — pure, validated)
               │
        ┌──────┴──────┐
        ▼             ▼
  Terminal         GUI (PySide6)
 renderer      MonitorWorker · InspectorWorker · ActionWorker
               (background threads — the dashboard never blocks)
```

The key architectural rule: **collectors never invoke `subprocess` directly.** All ADB execution is centralized in `adb/connection.py` (`ConnectionManager`, which satisfies the `CommandRunner` protocol that every collector and GUI worker consumes). Raw device output is parsed into normalized, frozen-dataclass models, and only those models reach the renderers — neither the terminal renderer nor the GUI widgets ever touch ADB or parse device text.

## 🔒 Safety & Design Principles

- **Read-only by construction.** The app only reads `/proc`, `/sys` and `dumpsys`/`pm` state. No process is started, stopped, killed, or re-prioritized except the three explicit, selected, package-verified device actions.
- **No arbitrary ADB shell.** The tool never forwards interactive or free-form shell input; every command is a fixed argument list.
- **Verified package identity.** No device action runs without the target being positively verified against the device's installed-package list; stale identities are invalidated immediately when a device action reports a package as no longer installed.
- **No fabricated data.** A value that cannot be read is reported as `N/A` — never an invented zero. Kernel threads show `N/A` memory (a kernel property); permission-protected `/proc/<pid>/io` shows `N/A`.
- **Validated inputs.** PIDs must be positive integers before any `/proc/<pid>` path is built; device-side paths are fixed constants, never user-interpolated strings.
- **Honest semantics.** "Resident" is `VmRSS`, not PSS (shared pages are double-counted) — the UI and docs say so. Socket attribution is by UID, not PID (Android's limitation), and the tool says so.
- **Single blindingly obvious source of truth:** `src/android_task_manager/__init__.py` (`__version__`) drives the package version, the Windows EXE version resource and the release tag.

## 🛠 Tech Stack

| Layer | Technology | Notes |
| --- | --- | --- |
| Language | Python ≥ 3.10 | core app uses only the standard library |
| Desktop GUI | PySide6 ≥ 6.5 (Qt for Python) | optional extra, `pip install ".[gui]"` |
| Device bridge | ADB (`adb shell`) | not bundled (see [Why is ADB not bundled?](#why-is-adb-not-bundled)) |
| Term renderer | custom, dependency-light | `terminal/renderer.py` |
| Windows packaging | PyInstaller ≥ 6 | one-file windowed + debug builds |
| Tests | pytest ≥ 7 | 734 tests, fixture-driven, GUI headless |
| CI/CD | GitHub Actions | Linux matrix (3.10–3.12) + Windows release build |
| Product site | Next.js 16 (static export) | hosted on GitHub Pages |

## 📁 Project Structure

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
│   ├── process/                      # ps identity + top metrics, classification, and the
│   │                                 #   read-only /proc/<pid> inspector (inspector_* modules)
│   ├── network_investigation/        # socket tables (tcp{,6},udp{,6}) + UID attribution
│   ├── incident/                     # incident report: models (schema) · builder
│   │                                 #   (deterministic aggregation) · renderers (JSON/HTML)
│   ├── action/                       # package verification + Open App / App Info / Force Stop
│   ├── terminal/                     # dependency-light text renderer
│   ├── gui/                          # PySide6 dashboard: widgets/, workers (incl. incident
│   │                                 #   export worker + PDF writer), styles, setup panel,
│   │                                 #   entry point (app.py -> main)
│   └── main.py                       # terminal entry point / sample loop
├── tests/                            # 734 pytest tests (33 modules), fixed-device fixtures
├── packaging/                        # build_windows.ps1, icon + version-resource assets,
│   │                                 #   entry stubs (entry_gui.py / entry_console.py)
├── docs/                             # engineering research (e.g. m14-network-research.md)
├── android-task-manager-website/     # Next.js product website (static export -> out/)
├── .github/workflows/                # ci.yml · release.yml · deploy-pages.yml
├── pyproject.toml                    # single version authority (dynamic from __init__.py)
├── LICENSE                           # MIT
└── README.md
```

## 🚀 Download & Run (end users — no Python needed)

1. Download **`AndroidTaskManager.exe`** (a self-contained PySide6 build) from the [latest release](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v0.2.0/AndroidTaskManager.exe) — or from the [product website](https://kalyandhoni234-hash.github.io/Android-task-manager/), which links directly to the exact published artifact and shows its SHA-256 checksum.
2. Double-click the EXE. You do **not** need Python, git or the source tree.
3. The **connection-setup screen** walks you through the only remaining requirement — ADB + a connected device (details in the GUI section below).
4. The live dashboard appears. Monitoring is read-only; the three device actions are explicit and require a selection.

The EXE carries the product icon and a Windows version resource (product version = release version, from the single version source). On first launch, Windows SmartScreen may warn about an unsigned executable — it is a portable build that only talks to your device over ADB; choose *More info → Run anyway* if you trust the source (this is where the published SHA-256 checksum lets you verify the file you ran).

## 🔌 Android & ADB Setup

1. **Enable Developer Options** on the device: *Settings → About phone* → tap *Build number* seven times.
2. **Enable USB debugging**: *Settings → System → Developer options* → turn on **USB debugging**.
3. **Install Android Platform Tools** on your PC: download the official build from the [Android developer site](https://developer.android.com/tools/releases/platform-tools) and unzip it, e.g. to `C:\platform-tools` (contains `adb.exe`). ADB does **not** need to be on `PATH` — the app can find it (see below).
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

## 🧑💻 Development

Prerequisites: Python ≥ 3.10, git, and for GUI work an Android device (or rely on the test fixtures — no device required for the suite).

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

### Terminal mode flags

| Flag | Meaning | Default |
| --- | --- | --- |
| `--adb PATH` | Path to the `adb` executable (normally located automatically) | auto-detect |
| `--device SERIAL` | Explicit adb serial of the target device | auto-detect |
| `--interval SECONDS` | Seconds between CPU samples | `2.0` |
| `--samples N` | Stop after N samples (omit for an endless loop; Ctrl+C stops) | run forever |
| `--memory-interval SECONDS` | Seconds between `/proc/meminfo` reads | `10.0` |
| `--process-interval SECONDS` | Seconds between `ps`/`top` process refreshes | `5.0` |
| `--battery-interval SECONDS` | Seconds between `dumpsys battery` reads | `15.0` |
| `--network-interval SECONDS` | Seconds between `/proc/net/dev` reads | `5.0` |
| `--network-investigation-interval SECONDS` | GUI only: seconds between socket-table reads | `10.0` |
| `--timeout SECONDS` | Per-command timeout | `10.0` |

Notes: `--interval` is the tick rate; the other intervals are typically slower because the underlying reads are more expensive (processes) or the data changes slowly (memory, battery) — cached snapshots are re-rendered in between. The **first** CPU and network samples report `N/A`: both measurements are deltas, so real values appear from the second sample onward.

The GUI accepts the same `--adb`, `--device`, `--interval`, `--process-interval`, `--battery-interval`, `--memory-interval`, `--network-interval`, `--network-investigation-interval` and `--timeout` flags; it has no `--samples` flag.

### GUI layout (top to bottom)

- **Device** — manufacturer/model label, Android version, live connection state (connected / no device / ADB not found / offline / multiple devices / not authorized / timed out).
- **CPU** — overall utilization, the recent-history graph, one bar per core with frequency.
- **Memory** — available memory as the headline figure, a used-share bar, Total / Free / Cached / Buffers breakdown, history graph.
- **Processes** — table (PID, CPU, MEM, STATE, NAME) sorted by CPU, with filtering/sorting, classification, and the selectable **Process Inspector** panel (details + Network Connections).
- **Baseline & Security** — baseline capture, drift check with suspicious-signal section, and session export (JSON/CSV).
- **Incident Reporting** — generate, view (dialog with HTML preview) and export (JSON/HTML/PDF) the investigation report.
- **Battery** — level, status, health, temperature/voltage/technology/power source, history graph.
- **Network** — download/upload throughput, interface list grouped by type (active by default), history graph.

Before the dashboard appears, the **connection-setup screen** is shown whenever the app cannot reach exactly one device; it explains what is missing and how to fix it, auto-retries, and has a *Retry* button.

## 🧪 Testing

```bash
python -m pytest
```

The suite: **734 tests across 33 modules** (`tests/`), covering the parsers (CPU, memory, process, battery, network), delta calculations, collectors, the ADB discovery/connection layers, the package-identity resolver/service, the network investigation, the incident report layer (builder, JSON/HTML renderers, GUI panel/dialog/worker), and the GUI (widgets, setup flow, actions, workers).

- Runs entirely against **fixed fixtures based on verified Vivo V2026 output — no physical device required**.
- **GUI tests run headlessly** via Qt's `offscreen` platform plugin (`QT_QPA_PLATFORM=offscreen`): they construct widgets, deliver snapshots, drive the monitor worker, and cover the first-run setup flow (each connection state, the multi-device picker, ADB discovery) without a display.
- **Live Android-device testing is separate from CI**: USB disconnect/reconnect, authorization and long-run stability checks are performed manually on real hardware and are intentionally not part of the automated suite.

## CI/CD

Live status: [![CI](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/kalyandhoni234-hash/Android-task-manager/actions/workflows/ci.yml)

Three workflows in `.github/workflows/`:

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `ci.yml` | push / PR | Full test suite on **Python 3.10 / 3.11 / 3.12** (headless Qt), `python -m build` package check, plus a website job (Next.js lint + static export under Node 22). |
| `release.yml` | tag `v*` | On **Windows**, runs `packaging/build_windows.ps1`, generates `SHA256SUMS.txt`, and publishes `AndroidTaskManager.exe`, `AndroidTaskManager-debug.exe` and the checksums to a GitHub Release (`softprops/action-gh-release`). |
| `deploy-pages.yml` | push to `master` (website paths) / manual | Builds the Next.js static export and deploys it to GitHub Pages. Note: repo settings must use **Source: GitHub Actions**. |

## 📦 Windows Distribution

`packaging/build_windows.ps1` builds everything locally too:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

It creates a clean `.venv-build`, installs the app + PyInstaller, and produces:

- `dist\AndroidTaskManager.exe` — windowed build for normal users.
- `dist\AndroidTaskManager-debug.exe` — console build that echoes connection-state transitions to stdout (diagnostics).

Both builds embed the product icon (`packaging/assets/atm.ico`) and a Windows version resource generated from the single version source (`packaging/make_version_file.py`). The script prints the SHA-256 of each EXE. Release CI builds the same artifacts on tags and attaches them to the GitHub Release.

## ⬇️ Releases

| Release | Assets |
| --- | --- |
| [v0.2.0](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/tag/v0.2.0) *(current)* | [`AndroidTaskManager.exe`](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v0.2.0/AndroidTaskManager.exe) — 49,086,120 bytes, SHA-256 `a46c3ac3fd99f04182515f00fbaed9600ee4c0f7dd23c2d9009d509d92293086` · `AndroidTaskManager-debug.exe` · `SHA256SUMS.txt` |
| [v0.1.0](https://github.com/kalyandhoni234-hash/Android-task-manager/releases/tag/v0.1.0) | earlier build |

Every release publishes its executables **together with `SHA256SUMS.txt`**, and the product website shows the checksum of the exact published EXE — so you can verify what you downloaded. Release pages: <https://github.com/kalyandhoni234-hash/Android-task-manager/releases>

## 🌐 Product Website

The product website — **<https://kalyandhoni234-hash.github.io/Android-task-manager/>** — is the landing page for end users: hero, feature walkthrough, the workflow diagram, a real dashboard screenshot, download CTA pointing at the exact published release artifact with its SHA-256, and an FAQ (including *"Why is ADB not bundled?"* and *"Is it really read-only?"*). It is a Next.js static export in `android-task-manager-website/website/`, deployed by CI to GitHub Pages.

## ⚠️ Limitations

The tool is honest about what it cannot guarantee across devices:

- **ADB is required** — there is no on-device agent; everything goes through `adb shell`.
- **Android permissions differ between devices.** Fields one device exposes may be hidden on another; the tool reports `N/A` instead of guessing.
- **`/proc/<pid>/io` may be unavailable** on many devices; I/O fields are optional and read defensively.
- **Kernel threads** (bracketed names like `[kworker/0:1]`) may not expose normal memory information — a kernel property, not a bug.
- **Network interface classification is heuristic** (Wi-Fi / Mobile Data / VPN / … guessed from names); the aggregate-traffic rule is documented, not guaranteed for every vendor's virtual interfaces.
- **RSS is not PSS.** The inspector's "Resident" is `VmRSS`; shared pages count for every owning process, so it is not a proportional measure of a single app's footprint.
- **Socket attribution is by UID, not PID** — Android exposes no per-socket PID to a non-root process. The tool says so rather than guessing.
- **Some information is Android/vendor dependent** (charge-counter units, sysfs layout, `top` column availability) and is reported as-is or as `N/A`.

## 🤝 Contributing

Contributions are welcome. Please keep the project's invariants intact:

- **Stay read-only.** New collectors must not modify device state.
- **Verify identity claims.** Any new device action must pass the same package-identity verification; never act on an unverified package.
- **No free-form shell.** New commands must be fixed argument lists through `ConnectionManager`.
- **`N/A` over guessing.** New fields must report unavailability honestly, never fabricated zeros.
- **Tests.** Add fixtures-driven tests (no physical device needed) and make sure `python -m pytest` stays green.

Open an issue or pull request on GitHub — see the [issues](https://github.com/kalyandhoni234-hash/Android-task-manager/issues) page.

## 📄 License

MIT — see [LICENSE](LICENSE).

## 👤 Author

**Guru Sharan Kalyan** — B.Tech CSE (Cyber Security), Government Engineering College Ajmer.

- GitHub: [kalyandhoni234-hash](https://github.com/kalyandhoni234-hash)
- LinkedIn: [Guru Sharan Kalyan](https://www.linkedin.com/in/guru-sharan-kalyan-gr718/)

---

<div align="center">

**Built for Android monitoring, debugging and process investigation.**

</div>