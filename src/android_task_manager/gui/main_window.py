"""Main dashboard window: sections wired to the monitor's signals."""

from __future__ import annotations

import time as _time
from dataclasses import replace
from datetime import datetime

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
from ..action import DISABLE, FORCE_STOP, UNINSTALL, ActionResult, supported_actions
from ..applications import AppCategory, AppDetails, ApplicationSnapshot
from ..automation import AutomationEngine, AutomationTask
from ..background import (
    BackgroundAppsSnapshot,
    LastSeenTracker,
    build_background_apps,
)
from ..background.models import ForegroundSnapshot
from ..baseline import (
    BaselineSnapshot,
    BaselineStore,
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
from ..device_report import DeviceReportPayload, device_report_filename
from ..diagnostics.evaluate import evaluate as evaluate_diagnostics
from ..diagnostics.models import DiagnosticReport, DiagnosticSeverity
from ..health import DeviceHealth, evaluate_device_health
from ..heuristics import HeuristicReport
from ..history.session import (
    METRIC_BATTERY,
    METRIC_CPU,
    METRIC_MEMORY,
    METRIC_STORAGE,
    SessionHistory,
)
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
from ..recommend import Recommendation, recommend
from ..rules import Rule, RuleEngine, RuleOperator, RuleSeverity
from ..storage.models import StorageSnapshot
from ..thresholds import (
    BATTERY_LEVEL_ELEVATED_PERCENT,
    BATTERY_LEVEL_HIGH_PERCENT,
    CPU_HIGH_PERCENT,
    MEMORY_USED_HIGH_PERCENT,
    STORAGE_USED_HIGH_PERCENT,
)
from ..timeline import (
    EVENT_ACTION_EXECUTED,
    EVENT_DEVICE_CONNECTED,
    EVENT_DEVICE_DISCONNECTED,
    EVENT_HEALTH_CHANGED,
    EVENT_RECOMMENDATION,
    EVENT_RULE_FIRED,
    EventTimeline,
)
from ..updater import UpdateCheckResult
from .apps_page import ApplicationsPage
from .connection_strip import ConnectionStrip
from .device_page import DevicePage
from .diagnostics_dialog import DiagnosticsDialog
from .diagnostics_page import DiagnosticsPage
from .findings_page import FindingsPage
from .incident_dialog import IncidentDialog
from .intelligence_page import IntelligencePage, IntelligenceState
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


def _memory_used_percent(memory: MemorySnapshot | None) -> float | None:
    """Used share of total RAM (used = total − available); None when unknown."""
    if memory is None or memory.total_kb <= 0:
        return None
    used = max(0, memory.total_kb - memory.available_kb)
    return used / memory.total_kb * 100


# ---------------------------------------------------------------------------
# Builtin intelligence rules (canonical thresholds, never restated values)
# ---------------------------------------------------------------------------

_BUILTIN_RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="cpu_high",
        metric=METRIC_CPU,
        operator=RuleOperator.GE,
        threshold=CPU_HIGH_PERCENT,
        severity=RuleSeverity.WARNING,
        title="CPU utilization is high",
        description="Aggregate CPU utilization reaches the high threshold.",
        cooldown=60.0,
    ),
    Rule(
        rule_id="cpu_sustained_high",
        metric=METRIC_CPU,
        operator=RuleOperator.GE,
        threshold=CPU_HIGH_PERCENT,
        severity=RuleSeverity.CRITICAL,
        title="CPU utilization sustained high",
        description="Aggregate CPU utilization stays at/above the high threshold.",
        duration=60.0,
        cooldown=300.0,
    ),
    Rule(
        rule_id="memory_high",
        metric=METRIC_MEMORY,
        operator=RuleOperator.GE,
        threshold=MEMORY_USED_HIGH_PERCENT,
        severity=RuleSeverity.WARNING,
        title="Memory pressure is high",
        description="Used memory reaches the high threshold.",
        cooldown=60.0,
    ),
    Rule(
        rule_id="memory_sustained_high",
        metric=METRIC_MEMORY,
        operator=RuleOperator.GE,
        threshold=MEMORY_USED_HIGH_PERCENT,
        severity=RuleSeverity.CRITICAL,
        title="Memory pressure sustained high",
        description="Used memory stays at/above the high threshold.",
        duration=120.0,
        cooldown=300.0,
    ),
    Rule(
        rule_id="battery_low",
        metric=METRIC_BATTERY,
        operator=RuleOperator.LE,
        threshold=BATTERY_LEVEL_ELEVATED_PERCENT,
        severity=RuleSeverity.WARNING,
        title="Battery level is low",
        description="Battery level is at/below the elevated threshold.",
        cooldown=300.0,
    ),
    Rule(
        rule_id="battery_critical",
        metric=METRIC_BATTERY,
        operator=RuleOperator.LE,
        threshold=BATTERY_LEVEL_HIGH_PERCENT,
        severity=RuleSeverity.CRITICAL,
        title="Battery level is critical",
        description="Battery level is at/below the critical threshold.",
        cooldown=600.0,
    ),
    Rule(
        rule_id="storage_high",
        metric=METRIC_STORAGE,
        operator=RuleOperator.GE,
        threshold=STORAGE_USED_HIGH_PERCENT,
        severity=RuleSeverity.WARNING,
        title="Storage utilization is high",
        description="Used internal storage reaches the high threshold.",
        cooldown=300.0,
    ),
)


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

    #: (package) the user selected an application row; the app forwards it
    #: to the apps worker's detail read (queued onto its thread).
    apps_detail_requested = Signal(str)

    #: The user asked to refresh the installed-application inventory.
    apps_refresh_requested = Signal()

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

    #: (path, DeviceReportPayload) the user picked a device-report target.
    device_report_export_requested = Signal(str, object)

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
        self.apps = ApplicationsPage()
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
        self._latest_network: NetworkSnapshot | None = None

        #: Most recent live storage snapshot (internal /data volume),
        #: published by the monitor on its own slow cadence.
        self._latest_storage: StorageSnapshot | None = None

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

        #: Persistent per-device baseline store (assigned by the app with
        #: the platform user-data directory). ``None`` in tests keeps the
        #: GUI hermetic: nothing is ever read or written without a store.
        self.baseline_store: BaselineStore | None = None

        #: Incident reporting GUI-layer state: the last heuristic report,
        #: the permission audits seen so far (bounded), the generated report
        #: and the (lazily created) viewer dialog.
        self._heuristics: HeuristicReport | None = None
        self._permission_audits: list[PackagePermissionAudit] = []
        self._incident_report: IncidentReport | None = None
        self._incident_dialog: IncidentDialog | None = None
        self._device_label: str | None = None
        self._android_version: str | None = None

        #: ADB serial of the connected device (published by the monitor's
        #: connection state; used for export filenames and baseline lookup).
        self._device_serial: str | None = None

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

        #: Device intelligence state (v0.8): the session history, the
        #: per-session event timeline, the builtin rules, the latest health
        #: evaluation, the derived recommendations and the automation
        #: engine. All pure/deterministic — they consume the snapshots the
        #: monitor already publishes (zero additional ADB traffic).
        self._session_history = SessionHistory()
        self._timeline = EventTimeline()
        self._rules = RuleEngine(_BUILTIN_RULES)
        self._health: DeviceHealth | None = None
        self._recommendations: tuple[Recommendation, ...] = ()
        self._rule_fires: tuple[str, ...] = ()
        self._automation = AutomationEngine()
        self._pending_automation_task: AutomationTask | None = None
        self._latest_app_snapshot: ApplicationSnapshot | None = None
        #: The connected apps worker (set by wire_apps); ``None`` when the
        #: window was not wired to one. Guarded before any label request.
        self._apps: object | None = None
        #: Most recent foreground (resumed-activity) signal from the device.
        #: ``None`` until the monitor has sampled it (or the device was lost).
        self._latest_foreground: ForegroundSnapshot | None = None
        #: Resolved human-readable labels keyed by package name (device APK
        #: reads, cached per session). Missing keys fall back to package name.
        self._app_labels: dict[str, str | None] = {}
        #: Packages for which a label resolution has already been requested
        #: this session — prevents re-requesting (and re-reading APKs for)
        #: labels that could not be resolved.
        self._label_requested: set[str] = set()
        #: Aggregated background-user-app view (rebuilt from the snapshots
        #: the monitor + apps worker already publish; no extra polling).
        self._background_apps: BackgroundAppsSnapshot | None = None
        #: Bounded last-seen annotation for background entries; cleared on
        #: every disconnect so no stale observation survives a reconnect.
        self._last_seen_tracker = LastSeenTracker()
        #: Package whose background-app details are currently being shown.
        self._background_selected: str | None = None
        #: Verified installed-package set (process-to-app identity link for
        #: recommendations). Starts empty, never guessed: force-stop targets
        #: are only proposed for packages the device has verified installed.
        self._verified_packages: set[str] = set()
        #: User-category packages (Phase M system-app protection): the only
        #: set force-stop recommendations may target. Derived from the
        #: inventory's authoritative category classification; starts empty.
        self._user_packages: set[str] = set()

        self.processes.inspection_requested.connect(self.inspect_requested.emit)
        self.processes.inspector.action_requested.connect(self._on_action_clicked)
        self.processes.inspector.manage_requested.connect(self._on_manage_requested)
        self.apps.refresh_requested.connect(self._on_apps_refresh_requested)
        self.apps.detail_requested.connect(self.apps_detail_requested.emit)
        self.apps.details.action_requested.connect(self._on_apps_action_clicked)
        self.apps.details.permission_audit_requested.connect(
            self.permission_audit_requested.emit
        )
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
        self.intelligence = IntelligencePage()
        self.intelligence.apply_requested.connect(self._on_recommendation_applied)
        self.intelligence.navigate_requested.connect(self._on_intelligence_navigate)
        self.intelligence.background_detail_requested.connect(
            self._on_background_detail_requested
        )
        self.intelligence.background_action_requested.connect(
            self._on_background_action_clicked
        )
        self.intelligence.background_permission_audit_requested.connect(
            self.permission_audit_requested.emit
        )
        self.intelligence.background_refresh_requested.connect(
            self._on_background_refresh
        )
        self.device_page.export_requested.connect(self._on_device_report_export_requested)

        self._pages = QStackedWidget()
        self._pages.setObjectName("pages")
        self._pages.addWidget(self.overview)  # 0: OVERVIEW
        self._pages.addWidget(self._scrolled(self.processes))  # 1: PROCESSES
        self._pages.addWidget(self._scrolled(self.network))  # 2: NETWORK
        self._pages.addWidget(self._scrolled(self.apps))  # 3: APPLICATIONS
        self._pages.addWidget(self._scrolled(self.security))  # 4: BASELINE
        self._pages.addWidget(self._scrolled(self.findings))  # 5: FINDINGS
        self._pages.addWidget(self._scrolled(self.device_page))  # 6: DEVICE
        self._pages.addWidget(self._scrolled(self._health_page()))  # 7: HEALTH
        self._pages.addWidget(self._scrolled(self.diagnostics_page))  # 8: DIAGNOSTICS
        self._pages.addWidget(self._scrolled(self.intelligence))  # 9: INTELLIGENCE

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
            "applications": 3,
            "baseline": 4,
            "findings": 5,
            "device": 6,
            "health": 7,
            "diagnostics": 8,
            "intelligence": 9,
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
                cpu_percent=(
                    self._latest_cpu.aggregate_utilization_percent
                    if self._latest_cpu is not None
                    else None
                ),
                memory_used_percent=_memory_used_percent(self._latest_memory),
                battery_level_percent=(
                    self._latest_battery.level_percent
                    if self._latest_battery is not None
                    else None
                ),
                storage_used_percent=(
                    self._latest_storage.used_percent
                    if self._latest_storage is not None
                    else None
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
    # Device intelligence (v0.8): pure evaluation over existing snapshots
    # ------------------------------------------------------------------

    def _record_metric_samples(self, timestamp: float | None) -> None:
        """Record one sample per live metric into the session history."""
        self._session_history.record(
            cpu_used_percent=(
                self._latest_cpu.aggregate_utilization_percent
                if self._latest_cpu is not None
                else None
            ),
            memory_used_percent=_memory_used_percent(self._latest_memory),
            battery_level_percent=(
                self._latest_battery.level_percent
                if self._latest_battery is not None
                else None
            ),
            storage_used_percent=(
                self._latest_storage.used_percent
                if self._latest_storage is not None
                else None
            ),
            timestamp=timestamp,
        )

    def _evaluate_intelligence(self) -> None:
        """Run the deterministic intelligence pipeline on the GUI thread.

        Pure evaluation over already-collected snapshots: history is
        recorded by the snapshot handlers, rules fire through the bounded
        session history, health is derived from the live mirrors, and
        recommendations follow deterministically. Timeline transitions
        record only meaningful state flips.
        """
        if self._connection_state is not ConnectionState.CONNECTED:
            self._health = None
            self._recommendations = ()
            self._rule_fires = ()
            self._refresh_intelligence()
            return
        now = _time.monotonic()
        fires = self._rules.evaluate(self._session_history, now)
        if fires:
            self._rule_fires = tuple(
                f"{fire.message}" for fire in fires
            )
            for fire in fires:
                self._timeline.record(
                    EVENT_RULE_FIRED,
                    f"Rule fired: {fire.message}",
                    f"{fire.rule_id} fired at monotonic {now:.0f}",
                    monotonic=now,
                    wall_clock=datetime.now(),
                    device_serial=self._device_serial,
                    severity=(
                        "critical"
                        if fire.rule_id in ("cpu_sustained_high", "memory_sustained_high", "battery_critical")
                        else "warning"
                    ),
                )
        else:
            self._rule_fires = ()
        self._evaluate_health(now)
        self._evaluate_recommendations(now)
        self._refresh_intelligence()

    def _evaluate_health(self, now: float) -> None:
        """Derive the unified device health from the latest snapshots."""
        health = evaluate_device_health(
            cpu=self._latest_cpu,
            memory=self._latest_memory,
            battery=self._latest_battery,
            storage=self._latest_storage,
            processes=self._latest_processes,
            network=self._latest_network,
            applications_available=self._latest_app_snapshot is not None,
            device_serial=self._device_serial,
            now=now,
        )
        previous_status = self._health.status if self._health is not None else None
        self._health = health
        if previous_status is not None and previous_status is not health.status:
            self._timeline.record_transition(
                "health",
                health.status.value,
                EVENT_HEALTH_CHANGED,
                f"Device health: {health.status.value}",
                (
                    f"Overall score {health.overall_score:.0f} — "
                    if health.overall_score is not None
                    else ""
                )
                + (
                    ", ".join(
                        f"{key}={component.status.value}"
                        for key, component in health.components.items()
                    )
                ),
                monotonic=now,
                wall_clock=datetime.now(),
                device_serial=self._device_serial,
                severity=health.status.value,
            )

    def _evaluate_recommendations(self, now: float) -> None:
        """Derive recommendations from the health findings; record new ones
        on the timeline (each distinct recommendation set once)."""
        recommendations = recommend(
            self._health,
            self._latest_processes,
            installed_packages=self._verified_packages,
            user_packages=self._user_packages,
        )
        if recommendations != self._recommendations:
            self._recommendations = recommendations
            if recommendations:
                for rec in recommendations:
                    self._timeline.record(
                        EVENT_RECOMMENDATION,
                        f"Recommendation: {rec.title}",
                        rec.rationale,
                        monotonic=now,
                        wall_clock=datetime.now(),
                        device_serial=self._device_serial,
                        severity=rec.severity,
                        entity=rec.target,
                    )
        self._refresh_intelligence()

    def _refresh_intelligence(self) -> None:
        """Render the intelligence engines' current outputs on the page."""
        self.intelligence.refresh(
            IntelligenceState(
                connected=self._connection_state is ConnectionState.CONNECTED,
                health=self._health,
                recommendations=self._recommendations,
                timeline=self._timeline.events,
                rule_fires=self._rule_fires,
                automation_tasks=self._automation.tasks,
                background_apps=self._background_apps,
            )
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
            self._latest_network = network
            self.network.set_snapshot(network)
        self._record_metric_samples(self._latest_cpu.timestamp if self._latest_cpu else None)
        self._evaluate_diagnostics()
        self._evaluate_intelligence()
        self._build_background_apps()
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

    def update_storage(self, snapshot: StorageSnapshot | None) -> None:
        """Adopt the monitor's latest storage snapshot (None = unavailable)."""
        self._latest_storage = snapshot
        self._record_metric_samples(_time.monotonic())
        self._evaluate_intelligence()
        self._refresh_overview()
        self._refresh_device_page()

    def update_foreground(self, snapshot: ForegroundSnapshot | None) -> None:
        """Adopt the device's current foreground-app signal and rebuild the
        background-app view (the foreground app must be excluded from it)."""
        self._latest_foreground = snapshot
        self._build_background_apps()

    # ------------------------------------------------------------------
    # Background user-app aggregation (pure build over existing snapshots)
    # ------------------------------------------------------------------

    def _build_background_apps(self) -> None:
        """Aggregate running processes into per-application background entries.

        Consumes ONLY snapshots the monitor and apps worker already publish
        (processes, memory, application inventory, foreground signal) plus the
        device-resolved label map. It owns no timer and never talks to ADB — a
        pure function over already-collected data, so it cannot introduce a
        second polling loop.

        When the device is disconnected (or telemetry is missing) the view is
        cleared, never left showing stale applications or CPU/RAM values.
        """
        connected = self._connection_state is ConnectionState.CONNECTED
        if (
            not connected
            or self._latest_processes is None
            or self._latest_app_snapshot is None
        ):
            self._background_apps = None
            if not connected:
                self._app_labels = {}
                self._label_requested = set()
                self._last_seen_tracker.clear()
                self._background_selected = None
            self.intelligence.set_background_apps(None)
            return

        snapshot = build_background_apps(
            self._latest_processes,
            self._latest_app_snapshot,
            self._latest_foreground,
            self._latest_memory,
            labels=self._app_labels,
        )
        snapshot = self._last_seen_tracker.annotate(snapshot, datetime.now())
        self._background_apps = snapshot
        self.intelligence.set_background_apps(snapshot)

        # Request labels only for packages not yet resolved this session, so
        # the one-off APK reads never repeat and never loop.
        if self._apps is not None:
            missing = [
                entry.package_name
                for entry in snapshot.entries
                if entry.package_name not in self._app_labels
                and entry.package_name not in self._label_requested
            ]
            if missing:
                self._label_requested.update(missing)
                self._apps.resolve_labels_requested.emit(missing)

    def on_app_labels_ready(self, labels: object) -> None:
        """Adopt resolved application labels and refresh the background view.

        A label is only ever ``None`` (unresolved) — the GUI keeps showing the
        package name for those; nothing is invented here.
        """
        if isinstance(labels, dict):
            self._app_labels.update(labels)  # type: ignore[arg-type]
        self._build_background_apps()

    def _on_background_detail_requested(self, package: str) -> None:
        """Track the selected background app and fetch its detail record."""
        self._background_selected = package
        self.apps_detail_requested.emit(package)

    def _on_background_refresh(self) -> None:
        """Rebuild the background view from the latest cached telemetry.

        Label reads are not re-triggered for already-resolved packages (the
        session cache holds), but the aggregation itself always re-runs so
        fresh process/memory/foreground samples are reflected immediately.
        """
        self._build_background_apps()

    def _on_background_action_clicked(self, action: str, package: str) -> None:
        """Gate a background-app action through the v0.7 capability rules.

        The gate is re-checked here (defense in depth): a system application
        can never receive a destructive request, and force-stop / disable /
        uninstall always require explicit confirmation naming the target.
        """
        if not package:
            return
        info = None
        if self._latest_app_snapshot is not None:
            info = next(
                (a for a in self._latest_app_snapshot.applications if a.package_name == package),
                None,
            )
        if info is None:
            return
        is_system = info.category is AppCategory.SYSTEM
        available = supported_actions(is_system=is_system, enabled=info.enabled)
        if action not in available:
            return
        if action in (FORCE_STOP, DISABLE, UNINSTALL) and not self._confirm_apps_action(
            action, package, "Confirm Application Action?"
        ):
            return
        self.intelligence.background_set_actions_busy(True)
        self.action_requested.emit(action, package)

    def update_devices(self, devices: list[dict[str, str]]) -> None:
        """Fill the multi-device picker on the setup screen."""
        self.setup.set_devices(devices)

    def update_connection(self, state: ConnectionState, detail: str) -> None:
        self._connection_state = state
        self.device.set_status(state, detail)
        self.connection_strip.set_state(state, detail)
        if state is ConnectionState.CONNECTED:
            self._stack.setCurrentIndex(1)
            self._timeline.record_transition(
                "device_connection",
                "connected",
                EVENT_DEVICE_CONNECTED,
                "Device connected",
                detail or "The device is connected.",
                monotonic=_time.monotonic(),
                wall_clock=datetime.now(),
                device_serial=self._device_serial,
            )
        else:
            # No device: stale identity facts and telemetry must never
            # linger on the pages — clear the mirrors the overview and the
            # device page render from.
            self.device_information = None
            self._latest_cpu = None
            self._latest_memory = None
            self._latest_battery = None
            self._latest_network = None
            self._latest_storage = None
            self._latest_processes = None
            self._latest_network_investigation = None
            self._latest_app_snapshot = None
            self._latest_foreground = None
            self._app_labels = {}
            self._label_requested = set()
            self._background_apps = None
            self._last_seen_tracker.clear()
            self._background_selected = None
            self._verified_packages = set()
            self._user_packages = set()
            self._diagnostics_report = None
            self._health = None
            self._recommendations = ()
            self._rule_fires = ()
            self._pending_automation_task = None
            self._device_serial = None
            self._timeline.record_transition(
                "device_connection",
                "disconnected",
                EVENT_DEVICE_DISCONNECTED,
                "Device disconnected",
                detail or "The device connection was lost.",
                monotonic=_time.monotonic(),
                wall_clock=datetime.now(),
            )
            self.diagnostics_page.refresh(None, False)
            self.apps.clear()
            self.intelligence.set_background_apps(None)
            self._stack.setCurrentIndex(0)
            self.setup.show_state(state, detail)
        self._refresh_intelligence()
        self._refresh_overview()
        self._refresh_device_page()

    def on_serial_ready(self, serial: str) -> None:
        """Adopt the connected device's ADB serial (monitor thread publishes
        it once per successful connection; zero additional ADB traffic).

        The serial drives the device-report filename and the persisted
        baseline lookup. A stored baseline from this exact device is
        auto-loaded only when no session baseline exists yet — a baseline
        captured in this session always wins over disk state.
        """
        self._device_serial = serial
        # Per-session intelligence state: history, timeline and cooldowns
        # belong to one device session and reset with it. The serial is
        # already read by the monitor's connect — no additional ADB traffic.
        now = _time.monotonic()
        self._session_history.begin_session(serial, timestamp=now)
        self._timeline.begin_session(serial, monotonic=now)
        self._rules.begin_session()
        self._automation.begin_session()
        self._auto_load_baseline()

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
        self.apps.show_action_result(result)
        self.intelligence.background_action_result(result)
        self.intelligence.background_set_actions_busy(False)
        if result.success and result.action in ("force_stop", "enable", "disable", "uninstall"):
            self.apps.set_actions_busy(False)
            if result.action in ("enable", "disable"):
                self.apps_detail_requested.emit(result.package_name)
            self.apps_refresh_requested.emit()
        self._finalize_automation_task(result)

    def _finalize_automation_task(self, result: ActionResult) -> None:
        """Record an automation task's outcome after the worker reported it.

        The automation engine's gates were checked before the request was
        dispatched (approval, destructive, cooldown, loop protection); this
        applies the engine's bookkeeping (cooldown, execution budget, task
        status) after the typed result, and logs the executed action on the
        timeline.
        """
        pending = self._pending_automation_task
        if pending is None:
            return
        if pending.action != result.action or pending.target != result.package_name:
            return
        self._pending_automation_task = None
        now = _time.monotonic()
        task = self._automation.record_result(
            pending.task_id, result.success, now, result.message
        )
        if task is not None:
            self._timeline.record(
                EVENT_ACTION_EXECUTED,
                (
                    f"Automation executed: {result.action} {result.package_name}"
                    if result.success
                    else f"Automation action failed: {result.action} {result.package_name}"
                ),
                task.message,
                monotonic=now,
                wall_clock=datetime.now(),
                device_serial=self._device_serial,
                severity="info",
                entity=result.package_name,
            )
        self._refresh_intelligence()

    def _on_intelligence_navigate(self, package: str) -> None:
        """Open the affected application's details from a recommendation.

        Identity is re-verified against the installed inventory before
        anything is requested (defense in depth: the recommendation only
        exists for verified packages, and the check is cheap here). The
        detail read itself runs on the apps worker's thread — no ADB work
        on the GUI thread. Unknown targets are honestly ignored.
        """
        if package not in self._verified_packages:
            return
        self._on_page_requested("applications")
        self.apps_detail_requested.emit(package)

    def _on_recommendation_applied(self, recommendation: Recommendation) -> None:
        """Apply a recommendation's action.

        Two safe paths, split by automation eligibility:

        * ``automation_allowed`` recommendations (never destructive) run
          through the automation engine: the user's click is the explicit
          approval, then the engine's gates (cooldown, loop protection)
          decide, and the action is dispatched to the action worker.
        * Everything else (destructive force-stop recommendations) runs
          through the standard v0.7 user-action path with the same explicit
          confirmation the application pages require — automation never
          touches destructive actions.
        """
        if recommendation.action is None or recommendation.target is None:
            return
        if recommendation.automation_allowed:
            self._apply_automated_recommendation(recommendation)
            return
        if recommendation.destructive and not self._confirm_apps_action(
            recommendation.action,
            recommendation.target,
            "Run Recommended Action?",
        ):
            return
        self.action_requested.emit(recommendation.action, recommendation.target)

    def _apply_automated_recommendation(self, recommendation: Recommendation) -> None:
        """Dispatch an automation-eligible recommendation safely."""
        now = _time.monotonic()
        task = self._automation.submit(recommendation, now)
        if task.status.value == "failed":
            QMessageBox.information(self, "Recommendation unavailable", task.message)
            self._refresh_intelligence()
            return
        task = self._automation.approve(task.task_id, now)
        if task is None:
            return
        gated = self._automation.gate(task.task_id, now)
        if gated is None:
            return
        if gated.status.value in ("blocked", "failed"):
            QMessageBox.information(self, "Action not run", gated.message)
            self._refresh_intelligence()
            return
        self._pending_automation_task = gated
        self.action_requested.emit(gated.action, gated.target)
        self._refresh_intelligence()

    def on_packages_ready(self, packages: set[str]) -> None:
        """Forward the verified package list to the inspector panel."""
        self.processes.inspector.set_packages(packages)
        self._verified_packages = set(packages)
        self._evaluate_intelligence()

    # ------------------------------------------------------------------
    # Application inventory handlers (GUI thread; results from AppsWorker)
    # ------------------------------------------------------------------

    def _on_apps_refresh_requested(self) -> None:
        """Flip the page into its loading state, then run the inventory
        read on the apps worker's thread."""
        self.apps.set_loading()
        self.apps_refresh_requested.emit()

    def on_apps_inventory_ready(self, snapshot: ApplicationSnapshot) -> None:
        """Adopt the fresh installed-application inventory."""
        self._latest_app_snapshot = snapshot
        self._verified_packages = {
            app.package_name for app in snapshot.applications
        }
        self._user_packages = {
            app.package_name
            for app in snapshot.applications
            if app.category is AppCategory.USER
        }
        self.apps.set_snapshot(snapshot)
        self._evaluate_intelligence()
        self._build_background_apps()
        self._refresh_overview()

    def on_apps_inventory_failed(self, message: str) -> None:
        """Show the honest inventory failure state."""
        self.apps.show_inventory_failed(message)

    def on_apps_details_ready(self, details: AppDetails) -> None:
        """Render one application's detail record in the apps panel."""
        self.apps.show_details(details)
        if self._background_selected is not None and details.package_name == self._background_selected:
            self.intelligence.show_background_details(details)

    def on_apps_details_failed(self, package: str, message: str) -> None:
        """Render the honest detail failure state."""
        self.apps.show_details_failed(package, message)

    def _on_apps_action_clicked(self, action: str, package: str) -> None:
        """Gate a clicked application action behind confirmation and
        capability validation, then forward it.

        The capability gate is re-checked here (defense in depth): a
        system application can never receive a destructive request even if
        its button state was computed from stale details. Force Stop,
        Disable and Uninstall always ask for explicit confirmation that
        names the target package first.
        """
        details = self.apps.details.current_details()
        if details is None or details.package_name != package:
            return
        from ..action import supported_actions

        is_system = details.category is AppCategory.SYSTEM
        available = supported_actions(is_system=is_system, enabled=details.enabled)
        if action not in available:
            return
        if action == "force_stop" and not self._confirm_apps_action(
            action, package, "Force Stop Application?"
        ):
            return
        if action == "disable" and not self._confirm_apps_action(
            action, package, "Disable Application?"
        ):
            return
        if action == "uninstall" and not self._confirm_apps_action(
            action, package, "Uninstall Application?"
        ):
            return
        self.apps.set_actions_busy(True)
        self.action_requested.emit(action, package)

    def _confirm_apps_action(self, action: str, package: str, title: str) -> bool:
        """Ask the user to explicitly confirm a destructive application
        action; every message names the exact target package."""
        warnings = {
            "force_stop": (
                "The application will be stopped. "
                "Its background services will not restart until it is opened again."
            ),
            "disable": (
                "The application will be disabled and will not run until re-enabled. "
                "It remains installed."
            ),
            "uninstall": (
                "The application and its data will be removed from the device. "
                "This cannot be undone."
            ),
        }
        message = (
            "This will apply to:\n"
            f"    {package}\n\n"
            f"{warnings.get(action, '')}\n\n"
            "Continue?"
        )
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_manage_requested(self, package: str) -> None:
        """Navigate from a process to its application management page.

        The package was verified against the installed list by the process
        inspector; the applications page selects it (falling back to a
        direct detail read when its inventory is stale or not yet loaded).
        """
        self._on_page_requested("applications")
        self.apps.select_package(package)

    # ------------------------------------------------------------------
    # Baseline & Security handlers (GUI thread; results from BaselineWorker)
    # ------------------------------------------------------------------

    def on_baseline_saved(
        self, snapshot: BaselineSnapshot, source: str = "created"
    ) -> None:
        """Adopt a fresh baseline; drift state resets with it.

        The previous report belongs to the old baseline, so the drift
        display, the NEW badges and the export buttons all reset honestly.

        ``source`` distinguishes a session capture (``"created"``) from a
        disk restore (``"loaded"``). Unless no store is configured, the
        baseline is also persisted per device — a write failure is shown
        as a status warning, never silently swallowed.
        """
        self._baseline = snapshot
        self._current_snapshot = None
        self._drift_report = None
        self._observation_tracker.reset()
        self._stability = None
        self.security.set_baseline(snapshot, source=source)
        self.processes.set_new_process_refs(frozenset())
        self.processes.inspector.set_new_socket_identities(frozenset())
        self._reset_incident_state()
        self._refresh_overview()
        if source == "created" and self.baseline_store is not None:
            try:
                self.baseline_store.save(snapshot)
            except OSError as exc:
                self.security.show_persist_failed(str(exc))

    def _auto_load_baseline(self) -> None:
        """Restore the stored baseline of the connected device.

        Runs once per connection, and only when no session baseline exists
        yet — a baseline captured in this session always wins over disk
        state. Missing/corrupt store files simply leave the empty state.
        """
        if self._baseline is not None or self.baseline_store is None:
            return
        if self._device_serial is None:
            return
        snapshot = self.baseline_store.load(self._device_serial)
        if snapshot is None:
            return
        self.on_baseline_saved(snapshot, source="loaded")

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
        """Render an audit result in the inspector and the apps panel, and
        keep a bounded record of recent audits for the incident report."""
        self.processes.inspector.show_permission_audit(audit)
        self.apps.show_permission_audit(audit)
        self._permission_audits.append(audit)
        if len(self._permission_audits) > 20:
            del self._permission_audits[:-20]
        self._refresh_overview()

    def on_permission_audit_failed(self, package: str, message: str) -> None:
        self.processes.inspector.show_permission_audit_failed(package, message)
        self.apps.show_permission_audit_failed(package, message)

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
    # Device report export (GUI thread assembles; worker writes)
    # ------------------------------------------------------------------

    def _on_device_report_export_requested(self) -> None:
        """Ask for a file target, assemble the payload, hand it to the worker.

        The payload is built from already-collected snapshots (zero ADB
        traffic) and the file write happens on the worker thread. A
        cancelled dialog is a clean no-op; no device means an honest status
        instead of an empty artifact.
        """
        if self._device_serial is None:
            self.device_page.show_export_result(
                False, "No device connected — nothing to export."
            )
            return
        generated_at = datetime.now()
        payload = DeviceReportPayload(
            info=self.device_information,
            battery=self._latest_battery,
            memory=self._latest_memory,
            cpu=self._latest_cpu,
            diagnostics=self._diagnostics_report,
            device_serial=self._device_serial,
            generated_at=generated_at,
        )
        default_name = device_report_filename(self._device_serial, generated_at)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export device report",
            default_name,
            "JSON file (*.json)",
        )
        if not path:
            return
        self.device_page.set_export_busy(True)
        self.device_report_export_requested.emit(path, payload)

    def on_device_report_export_completed(self, success: bool, message: str) -> None:
        self.device_page.show_export_result(success, message)

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
    worker.storage_snapshot.connect(window.update_storage)
    worker.device_info.connect(window.update_device)
    worker.device_information.connect(window.update_device_information)
    worker.connection_changed.connect(window.update_connection)
    worker.serial_ready.connect(window.on_serial_ready)
    worker.devices_available.connect(window.update_devices)
    worker.foreground_snapshot.connect(window.update_foreground)
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
    # The automation engine's gate requires a configured executor before any
    # dispatch; the GUI executor reuses the same async worker (the request is
    # queued onto its thread and the typed result returns through
    # ``action_completed`` → ``record_result``). The placeholder result is
    # never used by the GUI flow — the worker's real result supersedes it.
    def _dispatch(action: str, target: str) -> ActionResult:
        window.action_requested.emit(action, target)
        return ActionResult(
            action, target, True, "Dispatched to the action worker."
        )

    window._automation.set_executor(_dispatch)


def wire_apps(window: MainWindow, monitor: MonitorWorker, apps, actions) -> None:
    """Connect the application worker to the window, monitor and action
    worker.

    Inventory refresh requests run on the apps worker's thread (never the
    GUI); the action worker's installed-set refresh is triggered on the
    same requests so a successful uninstall/disable is reflected in the
    process inspector's identity checks immediately. The apps worker also
    resolves device-derived application labels (used by the background-app
    view) without any extra polling loop. ``window._apps`` is retained so
    the background builder can request label resolution on demand.
    """
    window._apps = apps
    window.apps_refresh_requested.connect(apps.refresh_inventory)
    window.apps_refresh_requested.connect(actions.reload_packages)
    window.apps_detail_requested.connect(apps.request_details)
    apps.inventory_ready.connect(window.on_apps_inventory_ready)
    apps.inventory_failed.connect(window.on_apps_inventory_failed)
    apps.details_ready.connect(window.on_apps_details_ready)
    apps.details_failed.connect(window.on_apps_details_failed)
    apps.labels_ready.connect(window.on_app_labels_ready)
    monitor.connection_changed.connect(apps.on_connection_changed)


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


def wire_device_report(window: MainWindow, worker) -> None:
    """Connect the DeviceReportWorker's signals to the window.

    The payload is assembled on the GUI thread from already-collected
    snapshots (pure, zero ADB); only the JSON write is handed to the
    worker. Results come back over queued connections; the GUI thread
    only renders.
    """
    window.device_report_export_requested.connect(worker.request_export)
    worker.export_completed.connect(window.on_device_report_export_completed)


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