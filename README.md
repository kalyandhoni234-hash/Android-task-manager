# Android Task Manager

A read-only Android/Linux system monitoring tool built with Python, ADB,
`/proc`, `/sys`, and Android system interfaces.

It shows CPU, memory, process, battery and network information from a
connected Android device — either as a live terminal dashboard or as a
PySide6 desktop GUI. Everything is read-only: the tool never starts, stops or
modifies processes and never writes to the device.

## Features

### CPU

- aggregate CPU utilization (deltas between two `/proc/stat` samples)
- per-core utilization
- per-core frequency (from `scaling_cur_freq` sysfs nodes)
- CPU history graph (GUI)

### Memory

- `MemAvailable` as the primary pressure indicator (not `MemFree`)
- used-memory share
- cached/buffer information

### Processes

- process table with PID, UID, state, CPU% and MEM%
- CPU/memory sorting (highest CPU first)
- process classification (kernel thread / system / user)
- Linux `/proc` process inspection on demand (GUI)

### Battery

- battery level
- charging state (status enum, normalized)
- health
- voltage
- temperature

### Network

- download/upload throughput (delta-based, bytes per second)
- interface classification (Wi-Fi / Mobile Data / VPN / …)
- active-interface filtering with a "show all" toggle (GUI)

### GUI

- PySide6 desktop dashboard
- live CPU graph
- process inspector detail panel

### Terminal

- terminal monitoring mode with configurable sampling cadences

## Architecture

```
Android Device
      │
      │ ADB
      ▼
ConnectionManager
      │
      ├── CPU Collector
      ├── Memory Collector
      ├── Process Collector
      ├── Battery Collector
      └── Network Collector
              │
              ▼
       Normalized Models
              │
       ┌──────┴──────┐
       ▼             ▼
   Terminal         GUI
                     │
              Process Inspector
                     │
                    /proc
```

The key rule of the codebase: **collectors never invoke `subprocess`
directly.** All ADB execution is centralized in `adb/connection.py`
(`ConnectionManager`, which satisfies the `CommandRunner` protocol that every
collector and the GUI workers consume). Raw device output is parsed and
normalized into frozen dataclass models, and only those models reach the
renderers — neither the terminal renderer nor the GUI widgets ever touch ADB
or parse device text.

Layout:

- `src/android_task_manager/adb/` — ADB subprocess execution + exceptions.
  **Only this package imports `subprocess`.**
- `src/android_task_manager/cpu/` — `/proc/stat` parsing, delta calculation,
  collector, normalized models.
- `src/android_task_manager/memory/` — `/proc/meminfo` parsing, collector,
  normalized models.
- `src/android_task_manager/process/` — `ps` identity + `top` metrics parsing,
  PID-based merging, classification, collector, plus the read-only `/proc/<pid>`
  inspector (`inspector_*` modules).
- `src/android_task_manager/battery/` — `dumpsys battery` parsing (with Android
  status/health enum normalization), collector, normalized models.
- `src/android_task_manager/network/` — `/proc/net/dev` parsing, delta
  throughput, traffic-interface aggregation, collector, normalized models.
- `src/android_task_manager/terminal/` — dependency-light text renderer.
- `src/android_task_manager/gui/` — PySide6 dashboard (widgets, monitor worker,
  process-inspection worker, styles, entry point).
- `src/android_task_manager/main.py` — terminal entry point / sample loop.

In the GUI, only the `MonitorWorker` and the `ProcessInspectionWorker` talk to
the ADB layer, and both run on background threads so the dashboard never
blocks.

## Requirements

- Python >= 3.10 *(build/running from source only — the packaged Windows
  executable does not need Python)*
- ADB (Android platform-tools) — located automatically (see **ADB
  discovery** below) or passed via `--adb`
- An Android device with USB debugging enabled, connected and authorized

The core application uses only the Python standard library. PySide6 is an
optional extra used by the GUI alone.

### ADB discovery

The app finds `adb` without you having to touch your `PATH`, in this priority
order:

1. The explicit path you passed (`--adb`, or "Locate ADB" in the GUI).
2. An `adb.exe` you placed next to the app itself (distribution-local copy).
3. `adb` on `PATH`.
4. Well-known Android SDK locations, detected safely (only when the file
   actually exists): `%ANDROID_HOME%/platform-tools`,
   `%ANDROID_SDK_ROOT%/platform-tools` and (Windows)
   `%LOCALAPPDATA%\Android\Sdk\platform-tools`.

ADB is **not bundled** with the app — see "Why is ADB not bundled?" below.

## Standalone Windows executable (no Python required)

For end users, a pre-built `AndroidTaskManager.exe` is the intended entry
point. It is a self-contained PySide6 application; you do **not** need to
install Python or any package.

- **First run** shows a connection-setup screen that guides you through the
  only remaining requirement (ADB + a connected device):
  - **ADB not found** → *Locate ADB* (pick `adb.exe`) or *How to install ADB*.
  - **No device detected** → connect the phone and enable USB debugging.
  - **Authorization required** → accept the USB debugging prompt on the phone.
  - **Device is offline** → reconnect the cable (or restart the adb server).
  - **Multiple devices** → choose which device to monitor.
- The screen **auto-retries** every couple of seconds, and you can hit *Retry*
  at any time — plugging in a phone, authorizing, or locating adb mid-session
  recovers without restarting the app.
- Once connected, the live dashboard appears and everything is read-only.

### Why is ADB not bundled?

The official `adb.exe` binaries are distributed under the [Android SDK License
Agreement](https://developer.android.com/tools/releases/platform-tools), whose
terms restrict redistribution. The safeguard is to let you supply `adb`
yourself: the app finds one you already have, or you download Platform-Tools
from Google and point the app at it (or drop `adb.exe` next to
`AndroidTaskManager.exe`). If you compile `adb` yourself from the [AOSP
source](https://android.googlesource.com/platform/packages/modules/adb/)
(Apache-2.0), you are free to distribute that binary with your own build.

### Build the Windows executable

Prerequisite: Python 3.10+ on `PATH` (only needed to build).

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

This creates a clean `.venv-build`, installs the app + PyInstaller, and
produces:

- `dist\AndroidTaskManager.exe` — windowed build for normal users.
- `dist\AndroidTaskManager-debug.exe` — console build that echoes connection
  state transitions to stdout (diagnostics).

## Installation (Windows, from source)

1. **Install Python** (>= 3.10) from <https://www.python.org/downloads/>.
   During installation, check **"Add python.exe to PATH"**.

2. **Install Android Platform Tools.** Download the Windows command-line tools
   from the [Android developer site](https://developer.android.com/tools/releases/platform-tools)
   and unzip them, e.g. to `C:\platform-tools`. Keep the location in mind —
   it contains `adb.exe`.

3. **Enable Developer Options on the device.** Open *Settings → About phone*
   and tap *Build number* seven times.

4. **Enable USB debugging.** In *Settings → System → Developer options*, turn
   on **USB debugging**.

5. **Connect the Android device** with a USB cable. When the device prompts
   "Allow USB debugging?", accept it and tick *Always allow from this
   computer*.

6. **Verify the connection** (from any terminal):

   ```bat
   C:\platform-tools\adb.exe devices
   ```

   Your device serial must appear in the `List of devices attached` section,
   marked `device` (not `unauthorized`).

7. **Install Android Task Manager:**

   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install .
   ```

   For the desktop GUI (optional):

   ```bat
   pip install ".[gui]"
   ```

ADB does not have to be globally installed. If `adb` is not on `PATH`, pass
its location explicitly, for example:

```bat
android-task-manager --adb "C:\path\to\platform-tools\adb.exe"
```

## Terminal usage

```bat
android-task-manager --help
android-task-manager
android-task-manager --adb "C:\platform-tools\adb.exe"
```

All flags:

| Flag | Meaning | Default |
| --- | --- | --- |
| `--adb PATH` | Path to the adb executable (normally located automatically) | auto-detect |
| `--device SERIAL` | Explicit adb serial of the target device | auto-detect |
| `--interval SECONDS` | Seconds between CPU samples | `2.0` |
| `--samples N` | Stop after N samples (omit for an endless loop; stop with Ctrl+C) | run forever |
| `--memory-interval SECONDS` | Seconds between `/proc/meminfo` reads | `10.0` |
| `--process-interval SECONDS` | Seconds between `ps`/`top` process refreshes | `5.0` |
| `--battery-interval SECONDS` | Seconds between `dumpsys battery` reads | `15.0` |
| `--network-interval SECONDS` | Seconds between `/proc/net/dev` reads | `5.0` |
| `--timeout SECONDS` | Per-command timeout | `10.0` |

Example: five samples, two seconds apart, using an explicit adb:

```bat
android-task-manager --adb "C:\platform-tools\adb.exe" --interval 2 --samples 5
```

Notes on the cadence flags:

- `--interval` is the tick rate; the other intervals are typically slower
  because the underlying reads are more expensive (processes) or the data
  changes slowly (memory, battery). Cached snapshots are re-rendered in
  between.
- The **first** CPU sample reports utilization as `N/A`: utilization is a
  delta between two samples, so real percentages appear from the second
  sample onward. The same is true for network throughput (`N/A` until a
  baseline exists).

## GUI usage

```bat
android-task-manager-gui
```

(or `android-task-manager-gui --adb "C:\platform-tools\adb.exe"` — the GUI
accepts the same `--adb`, `--device`, `--interval`, `--process-interval`,
`--battery-interval`, `--memory-interval`, `--network-interval` and
`--timeout` flags; it has no `--samples` flag.)

The dashboard shows, top to bottom:

- **Device** — manufacturer/model label, Android version, live connection
  state (connected / no device / ADB not found / offline / multiple devices /
  not authorized / timed out).

Before the dashboard appears, a **connection-setup screen** is shown whenever
the app cannot reach exactly one device; it explains what is missing and how
to fix it, with a *Retry* button (the app also auto-retries automatically).
- **CPU** — overall utilization, the recent-history graph, and one bar per
  core with frequency.
- **Memory** — available memory as the headline figure, a used-share bar, and
  the total/free/cached/buffers breakdown.
- **Processes** — a table of processes sorted by CPU usage (PID, CPU, MEM,
  STATE, NAME).
- **Battery** — level, status, health, and temperature/voltage/technology/
  power-source readouts.
- **Network** — download/upload throughput and an interface list grouped by
  type, filtered to active interfaces by default. Use **Show all interfaces**
  to reveal idle/loopback/virtual interfaces.

The application is **read-only**. Selecting a process row runs an on-demand
**Process Inspector** that reads the process's `/proc/<pid>/` files once
(never in a loop) and shows its state, threads, priority/nice, virtual and
resident memory, shared memory, command line and I/O counters. Inspections
run on a background worker thread, so the dashboard keeps sampling while the
read is in flight. If the process exits mid-inspection, the panel shows a
clean "Process no longer available" state.

Some fields may display **N/A**: Android permissions and vendor
implementations vary, so a value may be unavailable (for example a
permission-protected `/proc/<pid>/io`, or an unreadable sysfs frequency
node). `N/A` means "not available", never a fabricated zero.

## Technical limitations

The tool is honest about what it cannot guarantee across devices:

- **ADB is required.** There is no on-device agent; everything goes through
  `adb shell`.
- **USB or another supported ADB connection is required** (adb over Wi-Fi
  works the same way, but the device must be reachable by adb).
- **Android permissions differ between devices.** Fields that one device
  exposes may be hidden on another; the tool reports `N/A` instead of
  guessing.
- **`/proc/<pid>/io` may be unavailable** on many devices; I/O fields are
  optional and read defensively.
- **Kernel threads** (bracketed names like `[kworker/0:1]`) may not expose
  normal memory information — this is a kernel property, not a bug.
- **Network interface classification is heuristic** (Wi-Fi / Mobile Data /
  VPN / … are guessed from interface names) and the aggregate traffic rule is
  documented, not guaranteed correct for every vendor's virtual interfaces.
- **RSS is not PSS.** The inspector's "Resident" is `VmRSS`; shared pages are
  counted for every owning process and RSS is not a proportional measure of a
  single app's footprint.
- **`/storage/emulated` and `/data` must not be interpreted as independent
  physical storage** without qualification — this tool does not present them
  as storage volumes at all.
- **Some information is Android/vendor dependent** (e.g. charge counter units,
  sysfs layout, `top` column availability) and is reported as-is or as `N/A`.

## Security model

- The application is **read-only**: it reads `/proc`, `/sys` and `dumpsys`
  state and renders it. It does not modify Android system state.
- It is **dependent on ADB**: the security of the connection (USB debugging,
  RSA authorization) is ADB's, and the tool only uses `adb shell` to read
  files and run diagnostic commands.
- It is **not a process-management tool**: no process is started, stopped,
  killed, or re-prioritized.
- It is **not an arbitrary ADB shell**: the tool never forwards interactive
  or free-form shell input to the device; every command is a fixed argument
  list.
- **PID/path inputs are validated before use**: a PID must be a positive
  integer before a `/proc/<pid>` path is built (`process/inspector_collector.py`),
  and the GUI rejects non-numeric selections before they reach the worker.
  Device-side paths are fixed; no user-provided path is interpolated into a
  shell command.

## Process notes

- **Identity** comes from `ps -A -o PID,UID,NAME` (authoritative). Dynamic
  CPU and memory percentages come from `top -n 1` and are merged **by PID** —
  never by name or row order. `ps` lists hundreds of processes but `top`
  reports only the currently active ones, so the process table contains only
  processes `top` reported metrics for; `ps` supplies UID/name/category for
  those rows. ps-only processes (no dynamic metrics) are not rendered.
- `top` rows are parsed by whitespace tokens, anchored at the trailing
  `TIME+ %CPU %MEM S` columns and the name after them (robust to blank
  `PR/NI/...` cells, right-aligned columns, and ANSI row decoration).
  `%CPU` above 100 is kept as-is (multiple cores), not clamped and not
  divided by core count.
- Processes are classified by a documented heuristic, not a perfect taxonomy:
  bracketed names (`[kworker/...]`) → kernel thread; uid `< 10000` → system;
  otherwise → user/app. Unknown-uid processes (seen only in top) → system.
- The monitor's own `top -n 1` helper process is hidden from the GUI table.

## Process inspection (read-only)

Selecting a row in the GUI process table opens an inspection panel that reads
the process's `/proc/<pid>/` files once, on demand:

- `/proc/<pid>/status` — `Name`, `State`, `Uid` (real UID = first value),
  `Threads`, `VmSize` (→ Virtual), `VmRSS` (→ Resident), `RssAnon`,
  `RssFile`, `RssShmem` (→ Shared). Unknown keys and missing fields are
  ignored; each unavailable field is reported as `N/A`, never a fabricated
  zero.
- `/proc/<pid>/stat` — `priority`, `nice`, `num_threads`, `vsize`, `rss` as
  fallbacks. The `comm` group may contain spaces and parentheses, so the line
  is split on the first `(` / last `)` rather than by naive whitespace.
- `/proc/<pid>/cmdline` — NUL-separated argv, rendered space-joined. An empty
  cmdline shows `N/A`; nothing is invented from the process name.
- `/proc/<pid>/io` — optional. `read_bytes`/`write_bytes` when readable;
  permission errors or a missing file simply leave both as `N/A` and never
  fail the inspection. I/O throughput is not computed.

**Memory semantics.** Virtual = `VmSize` (address space). Resident = `VmRSS`
(physical pages in RAM); it is **not** PSS (proportional set size), not
"total RAM the app owns", and it double-counts pages shared with other
processes. Shared = `RssShmem` only.

**Process disappearance.** A process can exit between the table refresh, the
click, and the `/proc` read. The UI then shows a clean "Process no longer
available" state instead of crashing, and a fresh table refresh removes the
row.

## Memory notes

- `/proc/meminfo` values are normalized to integer KiB.
- `MemAvailable`, not `MemFree`, is the primary indicator of usable memory
  (cache is reclaimable). This is why the renderer shows Total / Available /
  Free / Cached / Buffers rather than a single "used" figure.
- For debugging, `MemorySnapshot.used_kb` = `total_kb - available_kb`
  (documented in `memory/models.py`); it is a pressure baseline, not a claim
  that cache is unreclaimable.

## Battery notes

- `dumpsys battery` values are key/value parsed: order-independent, unknown
  OEM fields tolerated, required fields validated.
- Raw Android `status`/`health` enum numbers are mapped to documented
  human-readable states; unknown values keep their raw number and normalize
  to `Unknown`.
- `temperature` (0.1 °C units) → °C in the model layer; `voltage` stays in mV
  (rendered as V); `level_percent = level / scale * 100` clamped to [0, 100].
  The `Power` line only reports connected sources (AC/USB/Wireless).

## CPU notes

- `busy = user + nice + system + irq + softirq`
- `total = busy + idle + iowait`
- `utilization = busy_delta / total_delta * 100`
- Fields after `softirq` (e.g. steal, guest, guest_nice) are ignored. Guest
  time is already counted inside `user`/`nice`, so it is not summed again.
- Utilization is always computed from **deltas between two samples**, never
  from a single `/proc/stat` snapshot.
- Per-core frequency is read from
  `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq`, normalized to kHz.
  A missing/unreadable node marks that core's frequency unavailable instead
  of crashing the monitor.

## Testing

```bash
python -m pytest
```

or, from a source checkout without installing:

```bash
pip install -e ".[dev,gui]"
python -m pytest
```

- The suite runs entirely against fixed fixtures based on verified Vivo V2026
  output — **no physical device is required**.
- **GUI tests run headlessly** using Qt's `offscreen` platform plugin
  (`QT_QPA_PLATFORM=offscreen`); they construct widgets, deliver snapshots,
  drive the monitor worker, and cover the first-run setup flow (each
  connection state, the multi-device picker, and ADB discovery) without a
  display.
- **Live Android-device testing is separate from CI.** USB
  disconnect/reconnect, authorization and long-run stability checks are
  performed manually on real hardware and are intentionally not part of the
  automated suite.
- CI (GitHub Actions, `.github/workflows/ci.yml`) runs the full suite on
  Python 3.10 / 3.11 / 3.12 and verifies the package builds.

## License

MIT — see [LICENSE](LICENSE).
