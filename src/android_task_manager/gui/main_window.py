"""Main dashboard window: sections wired to the monitor's signals."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..action.models import ActionResult
from ..baseline import (
    BaselineSnapshot,
    DriftReport,
    Session,
    new_process_refs,
    new_socket_identities,
)
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..heuristics import HeuristicReport
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..network_investigation.models import NetworkInvestigationSnapshot
from ..process.inspector_models import ProcessInspectionSnapshot
from ..process.models import ProcessSnapshot
from .monitor import ConnectionState, MonitorWorker
from .setup_panel import INSTALL_ADB_STEPS, USB_DEBUGGING_STEPS, SetupPanel
from .widgets.baseline_panel import BaselinePanel
from .widgets.battery_widget import BatteryWidget
from .widgets.cpu_widget import CPUWidget
from .widgets.device_widget import DeviceWidget
from .widgets.memory_widget import MemoryWidget
from .widgets.network_widget import NetworkWidget
from .widgets.process_widget import ProcessWidget


class MainWindow(QMainWindow):
    """Desktop dashboard consuming the monitor's normalized snapshots.

    The central area is a two-page stack: the first-run setup panel (shown
    until a device connects) and the live dashboard. Connection-state changes
    flip between the two pages.
    """

    #: Emitted when the window is closed; the app uses it to stop the worker.
    closed = Signal()

    #: (pid) the user selected a process row; the app forwards it to the
    #: inspection worker (queued onto that worker's thread).
    inspect_requested = Signal(object)

    #: The user asked to re-try the connection from the setup screen.
    retry_requested = Signal()
    #: The user asked to locate an adb executable via a file dialog.
    locate_requested = Signal()
    #: (serial) the user picked a device from the multi-device list.
    device_connect_requested = Signal(object)

    #: (action, package) the user confirmed a device action; the app
    #: forwards it to the action worker (queued onto that worker's thread).
    action_requested = Signal(str, str)

    #: The user asked to capture a fresh baseline (BaselineWorker).
    baseline_save_requested = Signal()
    #: (BaselineSnapshot) the user asked to check drift against this baseline.
    baseline_check_requested = Signal(object)
    #: (kind, path, Session) the user picked an export target.
    baseline_export_requested = Signal(str, str, object)
    #: (package) the user asked to audit a resolved package's permissions.
    permission_audit_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Android Task Manager {__version__}")
        self.resize(960, 760)

        self.setup = SetupPanel()
        self.setup.retry_requested.connect(self.retry_requested.emit)
        self.setup.locate_requested.connect(self.locate_requested.emit)
        self.setup.device_selected.connect(self.device_connect_requested.emit)
        self.setup.usb_help_requested.connect(self.show_usb_help)
        self.setup.install_help_requested.connect(self.show_install_help)
        self.setup.refresh_requested.connect(self.retry_requested.emit)

        self.device = DeviceWidget()
        self.cpu = CPUWidget()
        self.memory = MemoryWidget()
        self.processes = ProcessWidget()
        self.battery = BatteryWidget()
        self.network = NetworkWidget()
        self.security = BaselinePanel()

        #: Most recent ProcessSnapshot, kept so inspection results can be
        #: associated with the matching ProcessInfo (cpu/memory percent).
        self._latest_processes: ProcessSnapshot | None = None

        #: Most recent NetworkInvestigationSnapshot, kept so process
        #: inspections can render the UID-attributed socket view.
        self._latest_network_investigation: NetworkInvestigationSnapshot | None = None

        #: Baseline & Security GUI-layer state (in-memory; persistence is
        #: still deferred): the saved baseline, the current snapshot and the
        #: report of the last drift check.
        self._baseline: BaselineSnapshot | None = None
        self._current_snapshot: BaselineSnapshot | None = None
        self._drift_report: DriftReport | None = None

        self.processes.inspection_requested.connect(self.inspect_requested.emit)
        self.processes.inspector.action_requested.connect(self._on_action_clicked)
        self.security.save_requested.connect(self._on_security_save_requested)
        self.security.check_requested.connect(self._on_security_check_requested)
        self.security.export_requested.connect(self._on_export_requested)
        self.processes.inspector.permission_audit_requested.connect(
            self.permission_audit_requested.emit
        )

        top_row = QHBoxLayout()
        top_row.addWidget(self.cpu, 1)
        top_row.addWidget(self.memory, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self.battery, 1)
        bottom_row.addWidget(self.network, 1)

        content = QVBoxLayout()
        content.setContentsMargins(12, 2, 12, 2)
        content.setSpacing(6)
        content.addWidget(self.device)
        content.addLayout(top_row)
        content.addWidget(self.processes, 1)
        content.addWidget(self.security)
        content.addLayout(bottom_row)

        container = QWidget()
        container.setObjectName("dashboard")
        container.setLayout(content)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(container)

        self._stack = QStackedWidget()
        self._stack.addWidget(self.setup)
        self._stack.addWidget(scroll)
        self.setCentralWidget(self._stack)

    # ------------------------------------------------------------------
    # Monitor signal handlers (GUI thread)
    # ------------------------------------------------------------------

    def update_snapshots(
        self,
        cpu: CPUSnapshot,
        memory: MemorySnapshot | None,
        processes: ProcessSnapshot | None,
        battery: BatterySnapshot | None,
        network: NetworkSnapshot | None,
    ) -> None:
        self.cpu.set_snapshot(cpu)
        if memory is not None:
            self.memory.set_snapshot(memory)
        if processes is not None:
            self._latest_processes = processes
            self.processes.set_snapshot(processes)
        if battery is not None:
            self.battery.set_snapshot(battery)
        if network is not None:
            self.network.set_snapshot(network)

    def update_device(self, label: str, android_version: str) -> None:
        self.device.set_info(label, android_version)

    def update_network_investigation(
        self, snapshot: NetworkInvestigationSnapshot
    ) -> None:
        """Refresh the UID-attributed socket view, including an open panel."""
        self._latest_network_investigation = snapshot
        self.processes.inspector.set_network_data(snapshot)

    def update_devices(self, devices: list[dict[str, str]]) -> None:
        """Fill the multi-device picker on the setup screen."""
        self.setup.set_devices(devices)

    def update_connection(self, state: ConnectionState, detail: str) -> None:
        self.device.set_status(state, detail)
        if state is ConnectionState.CONNECTED:
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)
            self.setup.show_state(state, detail)

    def show_usb_help(self) -> None:
        QMessageBox.information(self, "Enable USB debugging", USB_DEBUGGING_STEPS)

    def show_install_help(self) -> None:
        QMessageBox.information(self, "Install ADB", INSTALL_ADB_STEPS)

    # ------------------------------------------------------------------
    # Process inspection result handlers (GUI thread)
    # ------------------------------------------------------------------

    def on_inspection_ready(self, snapshot: ProcessInspectionSnapshot) -> None:
        """Attach the table's latest CPU/MEM metrics, then render the panel."""
        info = None
        if self._latest_processes is not None:
            info = next(
                (p for p in self._latest_processes.processes if p.pid == snapshot.pid), None
            )
        if info is not None:
            snapshot = replace(
                snapshot,
                cpu_percent=info.cpu_percent,
                memory_percent=info.memory_percent,
            )
        self.processes.show_inspection(snapshot, self._latest_network_investigation)

    def on_inspection_failed(self, pid: int, message: str) -> None:
        """Show the clean "process no longer available" state."""
        self.processes.show_inspection_gone(pid, message)

    # ------------------------------------------------------------------
    # Device action handlers (GUI thread)
    # ------------------------------------------------------------------

    def _on_action_clicked(self, action: str, package: str) -> None:
        """Gate a clicked action behind confirmation, then forward it.

        The request is executed only when *package* still matches the
        *currently selected* process's verified identity: a stale context
        from a previously selected process is rejected outright. This is a
        defense in depth layer — the inspector already derives the package
        from its live selection at click time.

        Open App and App Info proceed immediately. Force Stop is
        destructive compared with monitoring: it always asks for explicit
        confirmation that identifies the target package first.
        """
        if package != self.processes.inspector.resolved_package():
            return
        if action == "force_stop" and not self._confirm_force_stop(package):
            return
        self.processes.inspector.set_actions_busy(True)
        self.action_requested.emit(action, package)

    def _confirm_force_stop(self, package: str) -> bool:
        """Ask the user to explicitly confirm a package force stop."""
        name = self.processes.inspector.display_name() or package
        answer = QMessageBox.question(
            self,
            "Force Stop Application?",
            "This will stop:\n"
            f"    {name}\n\n"
            f"Package:\n    {package}\n\n"
            "Force Stop the application?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def on_action_result(self, result: ActionResult) -> None:
        """Render the typed action outcome in the inspector panel."""
        self.processes.inspector.show_action_result(result)

    def on_packages_ready(self, packages: set[str]) -> None:
        """Forward the verified package list to the inspector panel."""
        self.processes.inspector.set_packages(packages)

    # ------------------------------------------------------------------
    # Baseline & Security handlers (GUI thread; results from BaselineWorker)
    # ------------------------------------------------------------------

    def on_baseline_saved(self, snapshot: BaselineSnapshot) -> None:
        """Adopt a fresh baseline; drift state resets with it.

        The previous report belongs to the old baseline, so the drift
        display, the NEW badges and the export buttons all reset honestly.
        """
        self._baseline = snapshot
        self._current_snapshot = None
        self._drift_report = None
        self.security.set_baseline(snapshot)
        self.processes.set_new_process_refs(frozenset())
        self.processes.inspector.set_new_socket_identities(frozenset())

    def on_baseline_failed(self, message: str) -> None:
        self.security.show_save_failed(message)

    def on_drift_checked(
        self,
        report: DriftReport,
        current: BaselineSnapshot,
        heuristics: HeuristicReport,
    ) -> None:
        """Render the drift check and project the NEW identities onto the
        existing process table and the inspector's socket table."""
        self._current_snapshot = current
        self._drift_report = report
        self.security.show_drift(report, heuristics)
        if self._baseline is None:
            return
        self.processes.set_new_process_refs(
            new_process_refs(report, self._baseline, current)
        )
        self.processes.inspector.set_new_socket_identities(
            new_socket_identities(report, self._baseline, current)
        )

    def on_drift_failed(self, message: str) -> None:
        self.security.show_drift_failed(message)

    def on_export_completed(self, success: bool, message: str) -> None:
        self.security.show_export_result(success, message)

    def _on_security_save_requested(self) -> None:
        """Flip the panel into its in-progress state, then run the save
        on the worker thread. Results release the lock via their own
        handlers."""
        self.security.set_save_busy(True)
        self.baseline_save_requested.emit()

    def _on_security_check_requested(self, baseline: BaselineSnapshot) -> None:
        self.security.set_check_busy(True)
        self.baseline_check_requested.emit(baseline)

    def _on_export_requested(self, kind: str) -> None:
        """Ask for a file target, then hand the session to the worker.

        A cancelled dialog is reported as such — the user never wonders
        whether an export ran. File writing itself happens on the worker
        thread, never on the GUI thread.
        """
        if self._baseline is None or self._current_snapshot is None or self._drift_report is None:
            return
        session = Session(baseline=self._baseline, current=self._current_snapshot, drift_report=self._drift_report)
        if kind == "json":
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export session JSON",
                "session.json",
                "JSON file (*.json)",
            )
        else:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Export drift events CSV",
                "drift-events.csv",
                "CSV file (*.csv)",
            )
        if not path:
            self.security.show_export_cancelled()
            return
        self.security.set_export_busy(True)
        self.baseline_export_requested.emit(kind, path, session)

    def on_permission_audit_ready(self, audit) -> None:
        """Render an audit result in the inspector (stale results are
        discarded there by package match)."""
        self.processes.inspector.show_permission_audit(audit)

    def on_permission_audit_failed(self, package: str, message: str) -> None:
        self.processes.inspector.show_permission_audit_failed(package, message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.closed.emit()
        super().closeEvent(event)


def wire(window: MainWindow, worker: MonitorWorker) -> None:
    """Connect a MonitorWorker's signals to the MainWindow slots."""
    worker.snapshots.connect(window.update_snapshots)
    worker.network_investigation.connect(window.update_network_investigation)
    worker.device_info.connect(window.update_device)
    worker.connection_changed.connect(window.update_connection)
    worker.devices_available.connect(window.update_devices)
    window.closed.connect(worker.stop)


def wire_inspector(window: MainWindow, inspector) -> None:
    """Connect the process-inspection worker to the window.

    ``inspect_requested`` is emitted on the GUI thread and delivered onto the
    inspector worker's own thread via Qt's queued connection, so /proc reads
    never block the dashboard. Results are delivered back the same way.
    """
    window.inspect_requested.connect(inspector.request_inspect)
    inspector.inspection_ready.connect(window.on_inspection_ready)
    inspector.inspection_failed.connect(window.on_inspection_failed)


def wire_actions(window: MainWindow, monitor: MonitorWorker, actions) -> None:
    """Connect the device-action worker to the window and monitor.

    Confirmed actions flow over a queued connection onto the action
    worker's thread; typed results come back the same way. The installed
    package list is refreshed every time the device (re)connects so action
    availability always reflects the connected device.
    """
    window.action_requested.connect(actions.request_action)
    actions.action_completed.connect(window.on_action_result)
    actions.packages_ready.connect(window.on_packages_ready)
    monitor.connection_changed.connect(
        lambda state, _detail: (
            actions.reload_packages() if state is ConnectionState.CONNECTED else None
        )
    )


def wire_security(window: MainWindow, worker) -> None:
    """Connect the BaselineWorker's signals to the window.

    Requests flow over queued connections onto the worker's thread; results
    (snapshots, reports, export outcomes) come back the same way. The GUI
    thread only renders.
    """
    window.baseline_save_requested.connect(worker.request_save_baseline)
    window.baseline_check_requested.connect(worker.request_drift_check)
    window.baseline_export_requested.connect(worker.request_export)
    worker.baseline_saved.connect(window.on_baseline_saved)
    worker.baseline_failed.connect(window.on_baseline_failed)
    worker.drift_checked.connect(window.on_drift_checked)
    worker.drift_failed.connect(window.on_drift_failed)
    worker.export_completed.connect(window.on_export_completed)


def wire_permissions(window: MainWindow, worker) -> None:
    """Connect the PermissionWorker to the window and the inspector."""
    window.permission_audit_requested.connect(worker.request_audit)
    worker.audit_ready.connect(window.on_permission_audit_ready)
    worker.audit_failed.connect(window.on_permission_audit_failed)