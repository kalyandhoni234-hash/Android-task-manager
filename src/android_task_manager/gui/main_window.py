"""Main dashboard window: sections wired to the monitor's signals."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer, Signal
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
from ..baseline.models import (
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
)
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation
from ..diagnostics.evaluate import evaluate as evaluate_diagnostics
from ..diagnostics.models import DiagnosticReport, DiagnosticSeverity
from ..heuristics import HeuristicReport
from ..incident.builder import build_incident_report
from ..incident.models import SOURCE_GUI, IncidentReport
from ..incident.renderers import report_filename
from ..investigation.attribution import attribute_sockets
from ..investigation.explain import entity_stability_for, explain_signal
from ..investigation.models import StabilityReport
from ..investigation.stability import ObservationTracker, stabilize_drift
from ..investigation.timeline import build_investigation_timeline
from ..investigation.tree import build_process_tree
from ..memory.models import MemorySnapshot
from ..network.models import NetworkSnapshot
from ..network_investigation.models import NetworkInvestigationSnapshot
from ..permissions.models import PackagePermissionAudit
from ..process.inspector_models import ProcessInspectionSnapshot
from ..process.models import ProcessSnapshot
from ..updater import UpdateCheckResult
from .connection_strip import ConnectionStrip
from .device_page import DevicePage
from .diagnostics_dialog import DiagnosticsDialog
from .diagnostics_page import DiagnosticsPage
from .findings_page import FindingsPage
from .incident_dialog import IncidentDialog
from .investigation_dialog import InvestigationDialog
from .monitor import ConnectionState, MonitorWorker
from .overview_page import OverviewPage, OverviewState
from .process_tree_dialog import ProcessTreeDialog
from .setup_panel import INSTALL_ADB_STEPS, USB_DEBUGGING_STEPS, SetupPanel
from .sidebar import DEFAULT_PAGE, Sidebar
from .update_banner import UpdateBanner
from .why_flagged_dialog import WhyFlaggedDialog
from .widgets.baseline_panel import BaselinePanel
from .widgets.battery_widget import BatteryWidget
from .widgets.cpu_widget import CPUWidget
from .widgets.device_widget import DeviceWidget
from .widgets.incident_panel import IncidentPanel
from .widgets.memory_widget import MemoryWidget
from .widgets.network_widget import NetworkWidget
from .widgets.process_widget import ProcessWidget


def _fmt_when(value) -> str:
    """Local-time, second-resolution timestamp for overview facts."""
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


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
    #: (path) the user chose an adb executable; delivered to the monitor
    #: worker's thread for validation and reconnect.
    adb_path_chosen = Signal(str)
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

    #: (kind, path, IncidentReport) the user picked an incident-report target.
    incident_export_requested = Signal(str, str, object)

    #: The user's session started; the app runs the one-shot update check.
    update_check_requested = Signal()

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

        self.update_banner = UpdateBanner()
        self.device = DeviceWidget()
        self.cpu = CPUWidget()
        self.memory = MemoryWidget()
        self.processes = ProcessWidget()
        self.battery = BatteryWidget()
        self.network = NetworkWidget()
        self.security = BaselinePanel()
        self.incident = IncidentPanel()

        #: Most recent ProcessSnapshot, kept so inspection results can be
        #: associated with the matching ProcessInfo (cpu/memory percent).
        self._latest_processes: ProcessSnapshot | None = None

        #: Most recent live snapshots, kept so the Device page can mirror a
        #: compact status summary without any additional ADB traffic.
        self._latest_cpu: CPUSnapshot | None = None
        self._latest_memory: MemorySnapshot | None = None
        self._latest_battery: BatterySnapshot | None = None

        #: Most recent NetworkInvestigationSnapshot, kept so process
        #: inspections can render the UID-attributed socket view.
        self._latest_network_investigation: NetworkInvestigationSnapshot | None = None

        #: The one-shot update check fires once, shortly after the window
        #: is shown; the flag keeps it from ever firing twice in a session.
        self._update_check_started = False

        #: Baseline & Security GUI-layer state (in-memory; persistence is
        #: still deferred): the saved baseline, the current snapshot and the
        #: report of the last drift check.
        self._baseline: BaselineSnapshot | None = None
        self._current_snapshot: BaselineSnapshot | None = None
        self._drift_report: DriftReport | None = None

        #: Incident reporting GUI-layer state: the last heuristic report,
        #: the permission audits seen so far (bounded), the generated report
        #: and the (lazily created) viewer dialog.
        self._heuristics: HeuristicReport | None = None
        self._permission_audits: list[PackagePermissionAudit] = []
        self._incident_report: IncidentReport | None = None
        self._incident_dialog: IncidentDialog | None = None
        self._device_label: str | None = None
        self._android_version: str | None = None

        #: Structured identity snapshot of the connected device (collected
        #: once per connection session); None when nothing is connected.
        self.device_information: DeviceInformation | None = None

        #: Most recent diagnostics report (pure evaluation of the latest
        #: snapshots + device information on the GUI thread). None when no
        #: device is connected — a report must never outlive its device.
        self._diagnostics_report: DiagnosticReport | None = None

        #: Investigation-core GUI-layer state: the observation window fed
        #: by the monitor (deduped, bounded), the stability reports of the
        #: last drift check, and the lazily created investigation dialogs.
        self._observation_tracker = ObservationTracker()
        self._stability: dict[str, StabilityReport] | None = None
        self._investigation_dialog: InvestigationDialog | None = None
        self._process_tree_dialog: ProcessTreeDialog | None = None
        self._why_dialog: WhyFlaggedDialog | None = None
        self._diagnostics_dialog: DiagnosticsDialog | None = None

        self.processes.inspection_requested.connect(self.inspect_requested.emit)
        self.processes.inspector.action_requested.connect(self._on_action_clicked)
        self.security.save_requested.connect(self._on_security_save_requested)
        self.security.check_requested.connect(self._on_security_check_requested)
        self.security.export_requested.connect(self._on_export_requested)
        self.security.timeline_requested.connect(self._on_timeline_requested)
        self.security.process_tree_requested.connect(self._on_process_tree_requested)
        self.security.why_requested.connect(self._on_why_requested)
        self.processes.inspector.permission_audit_requested.connect(
            self.permission_audit_requested.emit
        )
        self.incident.generate_requested.connect(self._on_incident_generate_requested)
        self.incident.view_requested.connect(self._on_incident_view_requested)
        self.incident.export_requested.connect(self._on_incident_export_requested)

        # -- Application shell: sidebar + pages ------------------------------
        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self._on_page_requested)
        self.sidebar.diagnostics_requested.connect(self._on_diagnostics_requested)
        self.connection_strip = ConnectionStrip()

        self.overview = OverviewPage()
        self.findings = FindingsPage(self.incident)
        self.findings.why_requested.connect(self._on_why_requested)
        self.device_page = DevicePage(self.device)
        self.diagnostics_page = DiagnosticsPage()

        self._pages = QStackedWidget()
        self._pages.setObjectName("pages")
        self._pages.addWidget(self.overview)  # 0: OVERVIEW
        self._pages.addWidget(self._scrolled(self.processes))  # 1: PROCESSES
        self._pages.addWidget(self._scrolled(self.network))  # 2: NETWORK
        self._pages.addWidget(self._scrolled(self.security))  # 3: BASELINE
        self._pages.addWidget(self._scrolled(self.findings))  # 4: FINDINGS
        self._pages.addWidget(self._scrolled(self.device_page))  # 5: DEVICE
        self._pages.addWidget(self._scrolled(self._health_page()))  # 6: HEALTH
        self._pages.addWidget(self._scrolled(self.diagnostics_page))  # 7: DIAGNOSTICS

        self.sidebar.set_active(DEFAULT_PAGE)
        self._pages.setCurrentIndex(0)
        self._connection_state: ConnectionState | None = None
        self._refresh_overview()

        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(0)
        right_column.addWidget(self.update_banner)
        right_column.addWidget(self.connection_strip)
        right_column.addWidget(self._pages, 1)

        shell = QWidget()
        shell.setObjectName("shell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.sidebar)
        shell_layout.addLayout(right_column, 1)

        self._stack = QStackedWidget()
        self._stack.addWidget(self.setup)
        self._stack.addWidget(shell)
        self.setCentralWidget(self._stack)
        self._refresh_device_page()

    @staticmethod
    def _scrolled(widget: QWidget) -> QScrollArea:
        """Wrap one page in a shared scroll area (frame-less, resizable)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _health_page(self) -> QWidget:
        """The HEALTH page: the existing CPU / memory / battery widgets."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self.cpu, 1)
        layout.addWidget(self.memory, 1)
        layout.addWidget(self.battery, 1)
        return page

    def _on_page_requested(self, key: str) -> None:
        """Switch to a page by its sidebar key; the pages stack order is
        fixed and created once, so navigation never rebuilds anything."""
        order = {
            "overview": 0,
            "processes": 1,
            "network": 2,
            "baseline": 3,
            "findings": 4,
            "device": 5,
            "health": 6,
            "diagnostics": 7,
        }
        index = order.get(key)
        if index is None:
            return
        self.sidebar.set_active(key)
        self._pages.setCurrentIndex(index)

    def _on_diagnostics_requested(self) -> None:
        """Open (or refresh) the local diagnostics dialog."""
        if self._diagnostics_dialog is None:
            self._diagnostics_dialog = DiagnosticsDialog(self)
        self._diagnostics_dialog.refresh()
        self._diagnostics_dialog.show()
        self._diagnostics_dialog.raise_()
        self._diagnostics_dialog.activateWindow()

    # ------------------------------------------------------------------
    # Overview / findings refresh (presentation only)
    # ------------------------------------------------------------------

    def _refresh_overview(self) -> None:
        """Summarize the existing GUI-layer state into the Overview page."""
        heuristics = self._heuristics
        high = sum(1 for s in heuristics.signals if s.severity == "HIGH") if heuristics else None
        medium = (
            sum(1 for s in heuristics.signals if s.severity == "MEDIUM")
            if heuristics
            else None
        )
        report = self._diagnostics_report
        self.overview.refresh(
            OverviewState(
                device_label=self._device_label,
                android_version=self._android_version,
                connection=self._connection_state,
                process_count=(
                    len(self._latest_processes.processes)
                    if self._latest_processes is not None
                    else None
                ),
                socket_count=(
                    len(self._latest_network_investigation.sockets)
                    if self._latest_network_investigation is not None
                    else None
                ),
                drift_count=(
                    len(self._drift_report.events) if self._drift_report is not None else None
                ),
                high_findings=high,
                medium_findings=medium,
                baseline_at=_fmt_when(self._baseline.created_at) if self._baseline else None,
                drift_checked_at=(
                    _fmt_when(self._drift_report.compared_at)
                    if self._drift_report is not None
                    else None
                ),
                audits_run=len(self._permission_audits),
                rules_checked=(
                    len(heuristics.rules_applied) if heuristics is not None else None
                ),
                signals_seen=len(heuristics.signals) if heuristics is not None else None,
                diagnostics_critical=(
                    report.counts[DiagnosticSeverity.CRITICAL] if report is not None else None
                ),
                diagnostics_warning=(
                    report.counts[DiagnosticSeverity.WARNING] if report is not None else None
                ),
                diagnostics_info=(
                    report.counts[DiagnosticSeverity.INFO] if report is not None else None
                ),
            )
        )

    def _refresh_findings(self) -> None:
        """Re-render the Findings page from the last heuristic report."""
        self.findings.show_heuristics(self._heuristics)

    def _refresh_device_page(self) -> None:
        """Mirror the structured identity + live snapshots onto the page."""
        self.device_page.refresh(
            self.device_information,
            self._latest_battery,
            self._latest_memory,
            self._latest_cpu,
            self._connection_state,
            self._diagnostics_report,
        )

    def _evaluate_diagnostics(self) -> None:
        """Evaluate the diagnostics rules over the latest collected data.

        Pure and deterministic — no device I/O, no timers, no new ADB
        traffic (it only consumes snapshots already flowing through the
        monitor). The page is refreshed only when the report actually
        changed, so widget churn is limited to genuine state changes.
        """
        report = evaluate_diagnostics(
            cpu=self._latest_cpu,
            memory=self._latest_memory,
            battery=self._latest_battery,
            device=self.device_information,
        )
        if report != self._diagnostics_report:
            self._diagnostics_report = report
            self.diagnostics_page.refresh(
                report,
                self._connection_state is ConnectionState.CONNECTED,
            )

    # ------------------------------------------------------------------
    # Monitor signal handlers (GUI thread)
    # ------------------------------------------------------------------

    def update_snapshots(
        self,
        cpu: CPUSnapshot | None,
        memory: MemorySnapshot | None,
        processes: ProcessSnapshot | None,
        battery: BatterySnapshot | None,
        network: NetworkSnapshot | None,
    ) -> None:
        """Adopt the monitor's latest snapshots.

        The monitor publishes an all-``None`` snapshot when the device is
        lost, so the GUI thread must tolerate it (and mirror the cleared
        state) instead of crashing on a stale-cache render.
        """
        self._latest_cpu = cpu
        if cpu is not None:
            self.cpu.set_snapshot(cpu)
        if memory is not None:
            self._latest_memory = memory
            self.memory.set_snapshot(memory)
        if processes is not None:
            self._latest_processes = processes
            self.processes.set_snapshot(processes)
            # Feed the investigation core's observation window (pure and
            # cheap; failures re-emit the cached snapshot with the same
            # timestamp, which the tracker dedupes).
            self._observation_tracker.record_process_snapshot(processes)
        if battery is not None:
            self._latest_battery = battery
            self.battery.set_snapshot(battery)
        if network is not None:
            self.network.set_snapshot(network)
        self._evaluate_diagnostics()
        self._refresh_overview()
        self._refresh_device_page()

    def update_device(self, label: str, android_version: str) -> None:
        self._device_label = label
        self._android_version = android_version
        self.device.set_info(label, android_version)
        self.connection_strip.set_device(label, android_version)
        self._refresh_overview()
        self._refresh_device_page()

    def update_device_information(self, info: DeviceInformation) -> None:
        """Adopt the structured identity snapshot of the connected device."""
        self.device_information = info
        self._evaluate_diagnostics()
        self._refresh_overview()
        self._refresh_device_page()

    def update_network_investigation(
        self, snapshot: NetworkInvestigationSnapshot
    ) -> None:
        """Refresh the UID-attributed socket view, including an open panel."""
        self._latest_network_investigation = snapshot
        self.processes.inspector.set_network_data(snapshot)
        self._observation_tracker.record_network_snapshot(snapshot)
        self._refresh_overview()

    def update_devices(self, devices: list[dict[str, str]]) -> None:
        """Fill the multi-device picker on the setup screen."""
        self.setup.set_devices(devices)

    def update_connection(self, state: ConnectionState, detail: str) -> None:
        self._connection_state = state
        self.device.set_status(state, detail)
        self.connection_strip.set_state(state, detail)
        if state is ConnectionState.CONNECTED:
            self._stack.setCurrentIndex(1)
        else:
            # No device: stale identity facts and telemetry must never
            # linger on the pages — clear the mirrors the overview and the
            # device page render from.
            self.device_information = None
            self._latest_cpu = None
            self._latest_memory = None
            self._latest_battery = None
            self._latest_processes = None
            self._latest_network_investigation = None
            self._diagnostics_report = None
            self.diagnostics_page.refresh(None, False)
            self._stack.setCurrentIndex(0)
            self.setup.show_state(state, detail)
        self._refresh_overview()
        self._refresh_device_page()

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
        self._observation_tracker.reset()
        self._stability = None
        self.security.set_baseline(snapshot)
        self.processes.set_new_process_refs(frozenset())
        self.processes.inspector.set_new_socket_identities(frozenset())
        self._reset_incident_state()
        self._refresh_overview()

    def _reset_incident_state(self) -> None:
        """A fresh baseline invalidates every incident artifact honestly:
        the report, the viewer and the underlying session data are cleared
        until the next drift check."""
        self._heuristics = None
        self._permission_audits = []
        self._incident_report = None
        self.incident.set_report(None)
        self.incident.set_generation_available(False)
        self._refresh_findings()

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
        self._heuristics = heuristics
        self.security.show_drift(report, heuristics)
        self.incident.set_generation_available(True)
        self._refresh_findings()
        self._refresh_overview()
        if self._baseline is None:
            return
        self._record_check_observations(current)
        self._stability = stabilize_drift(
            report,
            self._baseline,
            current,
            series={
                CATEGORY_PROCESS: self._observation_tracker.series(CATEGORY_PROCESS),
                CATEGORY_SOCKET: self._observation_tracker.series(CATEGORY_SOCKET),
            },
        )
        self.processes.set_new_process_refs(
            new_process_refs(report, self._baseline, current)
        )
        self.processes.inspector.set_new_socket_identities(
            new_socket_identities(report, self._baseline, current)
        )

    def _record_check_observations(self, current: BaselineSnapshot) -> None:
        """Append the drift-check's own snapshot to the observation window
        with its true completeness (verified -> COMPLETE, unverified with
        items -> PARTIAL, unverified and empty -> FAILED)."""
        from ..investigation.completeness import baseline_category_completeness

        timestamp = current.created_at.timestamp()
        self._observation_tracker.record(
            CATEGORY_PROCESS,
            baseline_category_completeness(current, CATEGORY_PROCESS),
            sorted(current.processes, key=lambda p: (p.process_name, p.uid)),
            timestamp=timestamp,
        )
        self._observation_tracker.record(
            CATEGORY_SOCKET,
            baseline_category_completeness(current, CATEGORY_SOCKET),
            sorted(
                current.sockets,
                key=lambda s: (s.protocol, s.local_address, s.local_port),
            ),
            timestamp=timestamp,
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
        """Render an audit result in the inspector and keep a bounded record
        of recent audits for the incident report."""
        self.processes.inspector.show_permission_audit(audit)
        self._permission_audits.append(audit)
        if len(self._permission_audits) > 20:
            del self._permission_audits[:-20]
        self._refresh_overview()

    def on_permission_audit_failed(self, package: str, message: str) -> None:
        self.processes.inspector.show_permission_audit_failed(package, message)

    # ------------------------------------------------------------------
    # Incident reporting handlers (GUI thread; build + exports)
    # ------------------------------------------------------------------

    def _on_incident_generate_requested(self) -> None:
        """Build a report from the current session data on the GUI thread.

        Generation is a pure, fast, deterministic aggregation of
        already-collected data — no device I/O, so it needs no worker. The
        report is dated by the generation moment (which is honest: that is
        when it was produced).
        """
        if self._baseline is None or self._current_snapshot is None or self._drift_report is None:
            self.incident.set_generating(False)
            return
        self.incident.set_generating(True)
        session = Session(
            baseline=self._baseline,
            current=self._current_snapshot,
            drift_report=self._drift_report,
        )
        report = build_incident_report(
            session=session,
            heuristics=self._heuristics,
            permission_audits=tuple(self._permission_audits),
            network_investigation=self._latest_network_investigation,
            process_snapshot=self._latest_processes,
            stability=tuple(self._stability.values()) if self._stability else None,
            source=SOURCE_GUI,
            device_label=self._device_label,
            android_version=self._android_version,
        )
        self._incident_report = report
        self.incident.set_report(report)

    def _on_incident_view_requested(self) -> None:
        """Open (or refresh) the report viewer dialog with the latest report."""
        if self._incident_report is None:
            return
        if self._incident_dialog is None:
            self._incident_dialog = IncidentDialog(self)
            self._incident_dialog.export_requested.connect(
                self._on_incident_export_requested
            )
        self._incident_dialog.show_report(self._incident_report)
        self._incident_dialog.show()
        self._incident_dialog.raise_()
        self._incident_dialog.activateWindow()

    def _on_incident_export_requested(self, kind: str) -> None:
        """Ask for a file target, then hand the report to the worker.

        A cancelled dialog is reported as such — the user never wonders
        whether an export ran. File writing happens on the worker thread,
        never on the GUI thread.
        """
        if self._incident_report is None:
            return
        report = self._incident_report
        default_name = report_filename(report.metadata.generated_at, kind)
        filters = {
            "json": "JSON file (*.json)",
            "html": "HTML file (*.html)",
            "pdf": "PDF file (*.pdf)",
        }
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export incident report",
            default_name,
            filters.get(kind, "All files (*)"),
        )
        if not path:
            self.incident.show_export_cancelled()
            return
        self.incident.set_export_busy(True)
        if self._incident_dialog is not None:
            self._incident_dialog.set_export_busy(True)
        self.incident_export_requested.emit(kind, path, report)

    def on_incident_export_completed(self, success: bool, message: str) -> None:
        self.incident.show_export_result(success, message)
        if self._incident_dialog is not None:
            self._incident_dialog.show_export_result(success, message)

    # ------------------------------------------------------------------
    # Investigation-core handlers (GUI thread; pure in-memory aggregation)
    # ------------------------------------------------------------------

    def _on_timeline_requested(self) -> None:
        """Open the investigation timeline for the current session.

        Like incident generation this is a pure, fast, deterministic
        aggregation of already-collected data — no device I/O, so it
        needs no worker.
        """
        if self._baseline is None or self._current_snapshot is None or self._drift_report is None:
            return
        session = Session(
            baseline=self._baseline,
            current=self._current_snapshot,
            drift_report=self._drift_report,
        )
        events = build_investigation_timeline(
            session=session,
            heuristics=self._heuristics,
            stability=self._stability,
            audits=tuple(self._permission_audits),
        )
        if self._investigation_dialog is None:
            self._investigation_dialog = InvestigationDialog(self)
        self._investigation_dialog.show_timeline(events)
        self._investigation_dialog.show()
        self._investigation_dialog.raise_()
        self._investigation_dialog.activateWindow()

    def _on_process_tree_requested(self) -> None:
        """Open the read-only process hierarchy of the latest snapshot."""
        if self._latest_processes is None:
            return
        tree = build_process_tree(self._latest_processes)
        if self._process_tree_dialog is None:
            self._process_tree_dialog = ProcessTreeDialog(self)
        self._process_tree_dialog.show_tree(
            tree, self._latest_network_investigation
        )
        self._process_tree_dialog.show()
        self._process_tree_dialog.raise_()
        self._process_tree_dialog.activateWindow()

    def _on_why_requested(self, signal) -> None:
        """Open the evidence facts behind one signal.

        The explanation is derived only from collected data; when the
        entity cannot be resolved the dialog says so honestly.
        """
        if self._baseline is None or self._current_snapshot is None or self._drift_report is None:
            return
        if self._why_dialog is None:
            self._why_dialog = WhyFlaggedDialog(self)
        explanation = explain_signal(
            signal,
            baseline=self._baseline,
            current=self._current_snapshot,
            drift=self._drift_report,
            processes=self._latest_processes,
            network_investigation=self._latest_network_investigation,
            audits=tuple(self._permission_audits),
            attribution=self._attribution_for_entity(signal.entity),
            entity_stability=self._stability_for_entity(signal.entity),
        )
        self._why_dialog.show_explanation(signal, explanation)
        self._why_dialog.show()
        self._why_dialog.raise_()
        self._why_dialog.activateWindow()

    def _attribution_for_entity(self, entity: str):
        """UID/PID attribution for a socket entity key, or None."""
        socket = self._socket_identity_for_entity(entity)
        if socket is None:
            return None
        attributed = attribute_sockets(
            (socket,),
            processes=self._latest_processes,
            uid_packages=(
                self._latest_network_investigation.uid_packages
                if self._latest_network_investigation is not None
                else None
            ),
            baseline=self._baseline,
            current=self._current_snapshot,
        )
        return attributed.get(socket)

    def _socket_identity_for_entity(self, entity: str):
        """Resolve a ``protocol:address:port`` entity to a SocketIdentity."""
        parts = entity.split(":")
        if len(parts) != 3:
            return None
        protocol, address, port = parts
        try:
            port_value = int(port)
        except ValueError:
            return None
        candidates = [
            s
            for s in self._current_snapshot.sockets
            if s.protocol == protocol and s.local_address == address and s.local_port == port_value
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda s: (s.remote_address or "", s.remote_port or -1, s.state or ""),
        )[0]

    def _stability_for_entity(self, entity: str):
        """The stability record for an entity key across categories."""
        if not self._stability:
            return None
        records = [
            record
            for report in self._stability.values()
            for record in report.entities
        ]
        return entity_stability_for(entity, records)

    # ------------------------------------------------------------------
    # Update check (one-shot, background worker, silent failures)
    # ------------------------------------------------------------------

    def on_update_check_completed(self, result: UpdateCheckResult) -> None:
        """Render the typed check outcome; failures simply hide the banner."""
        self.update_banner.show_result(result)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._update_check_started:
            self._update_check_started = True
            # Give the dashboard a moment to settle, then run the one-shot
            # check on the update worker's thread (never this one).
            QTimer.singleShot(1500, self.update_check_requested.emit)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.closed.emit()
        super().closeEvent(event)


def wire(window: MainWindow, worker: MonitorWorker) -> None:
    """Connect a MonitorWorker's signals to the MainWindow slots."""
    worker.snapshots.connect(window.update_snapshots)
    worker.network_investigation.connect(window.update_network_investigation)
    worker.device_info.connect(window.update_device)
    worker.device_information.connect(window.update_device_information)
    worker.connection_changed.connect(window.update_connection)
    worker.devices_available.connect(window.update_devices)
    window.closed.connect(worker.stop)
    window.overview.baseline_requested.connect(
        lambda: window._on_page_requested("baseline")
    )
    window.overview.diagnostics_requested.connect(
        lambda: window._on_page_requested("diagnostics")
    )


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
    # Connection transitions are forwarded to the action worker's own thread:
    # a CONNECTED state triggers the package-list refresh there, never on
    # the GUI thread (the old lambda ran in the emitting thread's context).
    monitor.connection_changed.connect(actions.on_connection_changed)


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


def wire_incident(window: MainWindow, worker) -> None:
    """Connect the IncidentWorker's signals to the window.

    Report generation stays on the GUI thread (pure aggregation); only the
    file exports are handed to the worker. Results come back over queued
    connections; the GUI thread only renders.
    """
    window.incident_export_requested.connect(worker.request_export)
    worker.export_completed.connect(window.on_incident_export_completed)


def wire_permissions(window: MainWindow, worker) -> None:
    """Connect the PermissionWorker to the window and the inspector."""
    window.permission_audit_requested.connect(worker.request_audit)
    worker.audit_ready.connect(window.on_permission_audit_ready)
    worker.audit_failed.connect(window.on_permission_audit_failed)


def wire_updates(window: MainWindow, worker) -> None:
    """Connect the UpdateWorker's signals to the window.

    The request flows over a queued connection onto the worker's thread
    (the GitHub API call never touches the GUI thread); the typed result
    comes back the same way. Failures are silent — the banner simply
    stays hidden.
    """
    window.update_check_requested.connect(worker.request_check)
    worker.check_completed.connect(window.on_update_check_completed)