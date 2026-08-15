"""GUI entry point (``android-task-manager-gui``).

Builds the QApplication, a background monitoring thread (reusing
ConnectionManager + the existing collectors unchanged), and the main window.
The GUI itself never calls adb / subprocess — only MonitorWorker does.

PySide6 imports are deferred to ``main()`` so that ``--help`` and the clean
"PySide6 not installed" message work without the GUI extra.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from ..adb.connection import ConnectionManager
from ..adb.discovery import find_adb, is_usable_adb, version_validator

_DEFAULT_INTERVAL = 2.0
_DEFAULT_MEMORY_INTERVAL = 10.0
_DEFAULT_PROCESS_INTERVAL = 5.0
_DEFAULT_BATTERY_INTERVAL = 15.0
_DEFAULT_NETWORK_INTERVAL = 5.0
_DEFAULT_NETWORK_INVESTIGATION_INTERVAL = 10.0


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
        "--timeout", type=float, default=10.0, help="Per-command timeout (default: %(default)s)."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Parse before importing PySide6 so `--help` works without the GUI extra.
    args = build_parser().parse_args(argv)

    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        from .action_worker import ActionWorker
        from .baseline_worker import BaselineWorker
        from .inspector_worker import ProcessInspectionWorker
        from .permission_worker import PermissionWorker

        from .main_window import (
            MainWindow,
            wire,
            wire_actions,
            wire_inspector,
            wire_permissions,
            wire_security,
        )
        from .monitor import MonitorWorker
        from .styles import DARK_STYLE
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
    worker = MonitorWorker(
        connection=connection,
        cpu_interval=args.interval,
        memory_interval=args.memory_interval,
        process_interval=args.process_interval,
        battery_interval=args.battery_interval,
        network_interval=args.network_interval,
        network_investigation_interval=args.network_investigation_interval,
    )
    inspector = ProcessInspectionWorker(connection=connection, timeout=args.timeout)
    actions = ActionWorker(connection=connection, timeout=args.timeout)
    baseline_worker = BaselineWorker(connection=connection, timeout=args.timeout)
    permission_worker = PermissionWorker(connection=connection, timeout=args.timeout)
    wire(window, worker)
    wire_inspector(window, inspector)
    wire_actions(window, worker, actions)
    wire_security(window, baseline_worker)
    wire_permissions(window, permission_worker)

    # First-run setup flow: the window asks; the shared connection + worker
    # react. Retry/relocate/device-pick are delivered onto the worker thread.
    window.retry_requested.connect(worker.retry)
    window.device_connect_requested.connect(worker.select_device)

    def on_locate_requested() -> None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _ = QFileDialog.getOpenFileName(
            window,
            "Locate adb executable",
            "",
            "adb executable (adb.exe;adb.bat;adb.cmd;adb)",
        )
        if chosen and is_usable_adb(chosen, version_validator(args.timeout)):
            connection.set_adb_path(str(chosen))
            worker.retry()

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

    baseline_thread = QThread()
    baseline_worker.moveToThread(baseline_thread)

    permission_thread = QThread()
    permission_worker.moveToThread(permission_thread)

    def shutdown() -> None:
        worker.stop()
        thread.quit()
        thread.wait(3000)
        inspector_thread.quit()
        inspector_thread.wait(3000)
        actions_thread.quit()
        actions_thread.wait(3000)
        baseline_thread.quit()
        baseline_thread.wait(3000)
        permission_thread.quit()
        permission_thread.wait(3000)

    app.aboutToQuit.connect(shutdown)

    thread.start()
    inspector_thread.start()
    actions_thread.start()
    baseline_thread.start()
    permission_thread.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())