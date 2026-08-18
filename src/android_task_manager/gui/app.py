"""GUI entry point (``android-task-manager-gui``).

Builds the QApplication, a background monitoring thread (reusing
ConnectionManager + the existing collectors unchanged), and the main window.
The GUI itself never calls adb / subprocess — only MonitorWorker does.

PySide6 imports are deferred to ``main()`` so that ``--help`` and the clean
"PySide6 not installed" message work without the GUI extra.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

from .. import __version__
from ..adb.connection import ConnectionManager
from ..adb.discovery import find_adb, version_validator
from ..baseline.storage import BaselineStore, user_data_dir
from ..core.diagnostics import setup_logging

logger = logging.getLogger("android_task_manager.gui")

_DEFAULT_INTERVAL = 2.0
_DEFAULT_MEMORY_INTERVAL = 10.0
_DEFAULT_PROCESS_INTERVAL = 5.0
_DEFAULT_BATTERY_INTERVAL = 15.0
_DEFAULT_NETWORK_INTERVAL = 5.0
_DEFAULT_NETWORK_INVESTIGATION_INTERVAL = 10.0
_DEFAULT_STORAGE_INTERVAL = 30.0

#: How long shutdown waits per worker thread. Bounded by the worst-case
#: in-flight work: a single ADB subprocess (``--timeout``, default 10 s)
#: plus scheduling slack. The monitor's connect path observes the stop
#: flag between commands, so a responsive device shuts down in well under
#: this budget; only a wedged adb can exceed it.
_SHUTDOWN_WAIT_MS = 15_000

#: Threads whose bounded shutdown wait expired (wedged adb). References are
#: kept alive so a running QThread is never destroyed mid-flight; the thread
#: finishes on its own once the in-flight call returns.
_ACTIVE_THREADS: list = []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android-task-manager-gui",
        description="Desktop dashboard for the Android Task Manager.",
    )
    parser.add_argument(
        "--adb",
        default=None,
        help=(
            "Path to the adb executable. When omitted, adb is located "
            "automatically (beside the app, on PATH, or in a standard SDK folder)."
        ),
    )
    parser.add_argument(
        "--device",
        dest="device_serial",
        default=None,
        help="Explicit adb serial of the target device.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=_DEFAULT_INTERVAL,
        help="Seconds between CPU samples (default: %(default)s).",
    )
    parser.add_argument(
        "--memory-interval",
        type=float,
        default=_DEFAULT_MEMORY_INTERVAL,
        help="Seconds between /proc/meminfo reads (default: %(default)s).",
    )
    parser.add_argument(
        "--process-interval",
        type=float,
        default=_DEFAULT_PROCESS_INTERVAL,
        help="Seconds between ps/top process refreshes (default: %(default)s).",
    )
    parser.add_argument(
        "--battery-interval",
        type=float,
        default=_DEFAULT_BATTERY_INTERVAL,
        help="Seconds between dumpsys battery reads (default: %(default)s).",
    )
    parser.add_argument(
        "--network-interval",
        type=float,
        default=_DEFAULT_NETWORK_INTERVAL,
        help="Seconds between /proc/net/dev reads (default: %(default)s).",
    )
    parser.add_argument(
        "--network-investigation-interval",
        type=float,
        default=_DEFAULT_NETWORK_INVESTIGATION_INTERVAL,
        help="Seconds between socket-table reads (default: %(default)s).",
    )
    parser.add_argument(
        "--storage-interval",
        type=float,
        default=_DEFAULT_STORAGE_INTERVAL,
        help="Seconds between internal-storage reads (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Per-command timeout (default: %(default)s)."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Parse before importing PySide6 so `--help` works without the GUI extra.
    args = build_parser().parse_args(argv)
    setup_logging()

    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        from .action_worker import ActionWorker
        from .apps_worker import AppsWorker
        from .baseline_worker import BaselineWorker
        from .device_report_worker import DeviceReportWorker
        from .incident_worker import IncidentWorker
        from .inspector_worker import ProcessInspectionWorker
        from .main_window import (
            MainWindow,
            wire,
            wire_actions,
            wire_apps,
            wire_device_report,
            wire_incident,
            wire_inspector,
            wire_permissions,
            wire_security,
            wire_updates,
        )
        from .monitor import MonitorWorker
        from .permission_worker import PermissionWorker
        from .styles import DARK_STYLE
        from .update_worker import UpdateWorker
    except ImportError:
        print(
            "The GUI requires PySide6. Install it with:\n"
            '  pip install -e ".[gui]"',
            file=sys.stderr,
        )
        return 1

    app = QApplication([sys.argv[0]])
    app.setApplicationName("Android Task Manager")
    app.setStyleSheet(DARK_STYLE)

    # One shared ConnectionManager: the monitoring worker samples snapshots on
    # its thread; the inspection worker reads /proc/<pid> files on its own.
    # ADB is discovered unless the user gave an explicit path; the setup screen
    # can later redirect the shared connection via "Locate ADB".
    adb_path = (
        find_adb(explicit=args.adb, validator=version_validator(args.timeout))
        or args.adb
        or "adb"
    )
    connection = ConnectionManager(
        adb_path=adb_path,
        timeout=args.timeout,
        device_serial=args.device_serial,
    )
    window = MainWindow()
    # Per-device baseline persistence: the platform user-data directory
    # (e.g. %LOCALAPPDATA%\AndroidTaskManager on Windows). The window
    # auto-loads a stored baseline per device and saves new ones here.
    window.baseline_store = BaselineStore(user_data_dir())
    worker = MonitorWorker(
        connection=connection,
        timeout=args.timeout,
        cpu_interval=args.interval,
        memory_interval=args.memory_interval,
        process_interval=args.process_interval,
        battery_interval=args.battery_interval,
        network_interval=args.network_interval,
        network_investigation_interval=args.network_investigation_interval,
        storage_interval=args.storage_interval,
    )
    inspector = ProcessInspectionWorker(connection=connection, timeout=args.timeout)
    actions = ActionWorker(connection=connection, timeout=args.timeout)
    apps = AppsWorker(connection=connection, timeout=args.timeout)
    baseline_worker = BaselineWorker(connection=connection, timeout=args.timeout)
    permission_worker = PermissionWorker(connection=connection, timeout=args.timeout)
    incident_worker = IncidentWorker()
    device_report_worker = DeviceReportWorker()
    update_worker = UpdateWorker(current_version=__version__)
    wire(window, worker)
    wire_inspector(window, inspector)
    wire_actions(window, worker, actions)
    wire_apps(window, worker, apps, actions)
    wire_security(window, baseline_worker)
    wire_permissions(window, permission_worker)
    wire_incident(window, incident_worker)
    wire_device_report(window, device_report_worker)
    wire_updates(window, update_worker)

    # First-run setup flow: the window asks; the shared connection + worker
    # react. Retry/relocate/device-pick are delivered onto the worker thread.
    window.retry_requested.connect(worker.retry)
    window.device_connect_requested.connect(worker.select_device)
    window.adb_path_chosen.connect(worker.locate_adb)

    def on_locate_requested() -> None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _ = QFileDialog.getOpenFileName(
            window,
            "Locate adb executable",
            "",
            "adb executable (adb.exe;adb.bat;adb.cmd;adb)",
        )
        if chosen:
            # Only the file dialog runs here; validation (`adb version`) and
            # the reconnect happen on the monitor worker's thread.
            window.adb_path_chosen.emit(str(chosen))

    window.locate_requested.connect(on_locate_requested)

    if os.environ.get("ATMAN_DEBUG"):
        worker.connection_changed.connect(
            lambda state, detail: print(
                f"[debug] state: {state.value} - {detail}", flush=True
            )
        )
        worker.device_info.connect(
            lambda label, version: print(
                f"[debug] device: {label} (Android {version})", flush=True
            )
        )

    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    inspector_thread = QThread()
    inspector.moveToThread(inspector_thread)

    actions_thread = QThread()
    actions.moveToThread(actions_thread)

    apps_thread = QThread()
    apps.moveToThread(apps_thread)

    baseline_thread = QThread()
    baseline_worker.moveToThread(baseline_thread)

    permission_thread = QThread()
    permission_worker.moveToThread(permission_thread)

    incident_thread = QThread()
    incident_worker.moveToThread(incident_thread)

    device_report_thread = QThread()
    device_report_worker.moveToThread(device_report_thread)

    update_thread = QThread()
    update_worker.moveToThread(update_thread)

    threads = [
        thread,
        inspector_thread,
        actions_thread,
        apps_thread,
        baseline_thread,
        permission_thread,
        incident_thread,
        device_report_thread,
        update_thread,
    ]

    def shutdown() -> None:
        # 1) Cooperative stop request: the monitor observes the flag between
        #    ADB commands and exits its timer loop; the other workers have no
        #    long-lived loop and are stopped by their event loops quitting.
        worker.stop()
        # 2) Ask every event loop to exit. The monitor thread must be out of
        #    its blocking ADB call first, so this is a request, not a kill.
        for thread in threads:
            thread.quit()
        # 3) Bounded wait. On a responsive device the monitor's in-flight
        #    command returns within ``--timeout`` and every thread finishes
        #    quickly; a wedged adb is the only way to exceed the budget.
        for thread in threads:
            if not thread.wait(_SHUTDOWN_WAIT_MS):
                logger.warning(
                    "thread %r still running after %d ms; keeping it alive "
                    "to avoid destroying a running QThread",
                    thread,
                    _SHUTDOWN_WAIT_MS,
                )
                _ACTIVE_THREADS.append(thread)

    app.aboutToQuit.connect(shutdown)

    thread.start()
    inspector_thread.start()
    actions_thread.start()
    apps_thread.start()
    baseline_thread.start()
    permission_thread.start()
    incident_thread.start()
    device_report_thread.start()
    update_thread.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())