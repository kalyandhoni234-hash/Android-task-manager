"""Headless GUI tests for the Baseline & Security feature area.

Offscreen Qt platform; never touches a device — workers are driven with
stubbed collectors/connections and the window renders stubbed results.
Covers: button enablement laws, drift summary, unverified note, process
table badges, signals section states, permissions tab honesty states,
export gating, and worker failure handling.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

from android_task_manager.adb.exceptions import ADBError, ADBTimeoutError
from android_task_manager.baseline import (
    BaselineSnapshot,
    ProcessRef,
    Session,
    diff_snapshot,
)
from android_task_manager.cpu.models import CPUSnapshot
from android_task_manager.gui.baseline_worker import BaselineWorker
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.permission_worker import PermissionWorker
from android_task_manager.gui.widgets.baseline_panel import BaselinePanel
from android_task_manager.gui.widgets.process_inspector_widget import ProcessInspectorWidget
from android_task_manager.gui.widgets.process_widget import ProcessWidget
from android_task_manager.heuristics import HeuristicReport, SuspiciousSignal, evaluate_heuristics
from android_task_manager.permissions import (
    CombinationFlag,
    PackagePermissionAudit,
    PermissionEntry,
)
from android_task_manager.permissions.models import PERMISSION_INSTALL, PERMISSION_RUNTIME
from android_task_manager.process.inspector_models import ProcessInspectionSnapshot
from android_task_manager.process.models import ProcessCategory, ProcessInfo, ProcessSnapshot

_AT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _proc(name: str, uid: int) -> ProcessRef:
    return ProcessRef(uid=uid, process_name=name, classification=ProcessCategory.USER)


def baseline_snapshot() -> BaselineSnapshot:
    return BaselineSnapshot(
        created_at=_AT,
        device_serial="TEST123",
        processes=frozenset({_proc("com.kept.app", 10002)}),
        packages=frozenset(),
        sockets=frozenset(),
    )


def current_snapshot() -> BaselineSnapshot:
    """Baseline plus one NEW process (com.new.app) — one drift event."""
    return BaselineSnapshot(
        created_at=_AT,
        device_serial="TEST123",
        processes=frozenset(
            {
                _proc("com.kept.app", 10002),
                _proc("com.new.app", 10003),
            }
        ),
        packages=frozenset(),
        sockets=frozenset(),
    )


def drift_check():
    """A stubbed worker result: (report, current, heuristics)."""
    baseline = baseline_snapshot()
    current = current_snapshot()
    report = diff_snapshot(baseline, current)
    return report, current, evaluate_heuristics(report, baseline, current)


def permission_audit(parse_complete: bool = True) -> PackagePermissionAudit:
    return PackagePermissionAudit(
        package_name="com.example.app",
        read_at=_AT,
        permissions=(
            PermissionEntry("android.permission.CAMERA", True, PERMISSION_RUNTIME),
            PermissionEntry("android.permission.INTERNET", False, PERMISSION_INSTALL),
            PermissionEntry("com.example.permission.PARTNER", None, PERMISSION_RUNTIME),
        ),
        parse_complete=parse_complete,
        combination_flags=(
            CombinationFlag(
                flag_id="SMS_ACCESSIBILITY_DEVICE_ADMIN",
                matched_permissions=(
                    "android.permission.READ_SMS",
                    "android.permission.BIND_ACCESSIBILITY_SERVICE",
                    "android.permission.BIND_DEVICE_ADMIN",
                ),
                description=(
                    "Requests SMS access alongside Accessibility Service and "
                    "Device Admin — a combination sometimes seen in "
                    "banking-trojan-style malware, worth reviewing why this "
                    "app needs all three."
                ),
            ),
        ),
    )


def _find_button(widget, text: str) -> QPushButton:
    for button in widget.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"no button labelled {text!r}")


def _labels_with_text(widget, text: str) -> list[QLabel]:
    """Labels whose text is exactly *text* and that are not explicitly
    hidden (a hidden note never counts). Detached/stale widgets are already
    excluded because they are no longer children."""
    return [
        label
        for label in widget.findChildren(QLabel)
        if label.text() == text
        and not (
            label.isHidden()
            and label.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
        )
    ]


# ---------------------------------------------------------------------------
# Baseline panel button laws
# ---------------------------------------------------------------------------


class TestBaselinePanelButtons:
    def test_check_drift_disabled_without_baseline_enabled_after_save(self, qtapp):
        window = MainWindow()
        panel = window.security
        check = _find_button(panel, "Check Drift")
        save = _find_button(panel, "Save Baseline")
        assert not check.isEnabled()
        assert save.isEnabled()
        window.on_baseline_saved(baseline_snapshot())
        assert check.isEnabled()
        assert not _find_button(panel, "Export JSON").isEnabled()
        assert not _find_button(panel, "Export CSV").isEnabled()

    def test_export_enabled_after_drift_check(self, qtapp):
        window = MainWindow()
        window.on_baseline_saved(baseline_snapshot())
        report, current, heuristics = drift_check()
        window.on_drift_checked(report, current, heuristics)
        assert _find_button(window.security, "Export JSON").isEnabled()
        assert _find_button(window.security, "Export CSV").isEnabled()

    def test_buttons_disabled_while_any_operation_is_in_flight(self, qtapp):
        panel = BaselinePanel()
        panel.set_baseline(baseline_snapshot())
        panel.set_save_busy(True)
        status = _labels_with_text(panel, "Reading a fresh baseline…")
        assert status
        assert not _find_button(panel, "Save Baseline").isEnabled()
        assert not _find_button(panel, "Check Drift").isEnabled()
        panel.set_save_busy(False)
        assert _find_button(panel, "Save Baseline").isEnabled()

    def test_save_failure_leaves_visible_status_and_releases_buttons(self, qtapp):
        panel = BaselinePanel()
        panel.set_save_busy(True)
        panel.show_save_failed("device offline")
        assert _labels_with_text(panel, "Baseline save failed: device offline")
        assert _find_button(panel, "Save Baseline").isEnabled()


# ---------------------------------------------------------------------------
# Drift summary + unverified note
# ---------------------------------------------------------------------------


class TestDriftSummary:
    def test_summary_strip_updates_after_drift_check(self, qtapp):
        window = MainWindow()
        window.on_baseline_saved(baseline_snapshot())
        report, current, heuristics = drift_check()
        window.on_drift_checked(report, current, heuristics)
        summary = window.security.findChild(QLabel, "driftSummary")
        assert summary.text() == "1 change(s) detected"
        assert "Last checked:" in window.security._checked_label.text()

    def test_unverified_note_shown_when_present_and_hidden_when_absent(self, qtapp):
        window = MainWindow()
        window.on_baseline_saved(baseline_snapshot())

        current = current_snapshot()
        current = BaselineSnapshot(
            created_at=current.created_at,
            device_serial=current.device_serial,
            processes=current.processes,
            packages=current.packages,
            sockets=current.sockets,
            processes_verified=False,
        )
        report = diff_snapshot(baseline_snapshot(), current)
        assert "process" in report.unverified_categories
        window.on_drift_checked(report, current, evaluate_heuristics(
            report, baseline_snapshot(), current
        ))
        note = _labels_with_text(window.security, "Could not verify: process")
        assert len(note) == 1
        assert not note[0].isHidden()

        clean_report, clean_current, clean_heuristics = drift_check()
        window.on_drift_checked(clean_report, clean_current, clean_heuristics)
        assert not _labels_with_text(window.security, "Could not verify: process")

    def test_zero_changes_reported_honestly(self, qtapp):
        window = MainWindow()
        base = baseline_snapshot()
        window.on_baseline_saved(base)
        report = diff_snapshot(base, base)
        heuristics = evaluate_heuristics(report, base, base)
        window.on_drift_checked(report, base, heuristics)
        assert window.security._drift_summary.text() == "0 change(s) detected"


# ---------------------------------------------------------------------------
# Process table NEW badges
# ---------------------------------------------------------------------------


class TestProcessTableBadges:
    def test_new_row_badged_and_clear_on_fresh_baseline(self, qtapp):
        widget = ProcessWidget()
        widget.set_snapshot(
            ProcessSnapshot(
                timestamp=1.0,
                processes=[
                    ProcessInfo(
                        pid=8150,
                        name="com.new.app",
                        uid=10003,
                        state="R",
                        cpu_percent=1.0,
                        memory_percent=1.0,
                        category=ProcessCategory.USER,
                    ),
                    ProcessInfo(
                        pid=8160,
                        name="com.kept.app",
                        uid=10002,
                        state="S",
                        cpu_percent=2.0,
                        memory_percent=1.0,
                        category=ProcessCategory.USER,
                    ),
                ],
            )
        )
        widget.set_new_process_refs(frozenset({_proc("com.new.app", 10003)}))
        table = widget.findChild(QTableWidget)
        rows = {}
        for row in range(table.rowCount()):
            pid = int(table.item(row, 0).text())
            rows[pid] = table.item(row, 4).text()
        assert rows[8150].startswith("[NEW] com.new.app")
        assert rows[8160] == "com.kept.app"

        widget.set_new_process_refs(frozenset())
        for row in range(table.rowCount()):
            assert not table.item(row, 4).text().startswith("[NEW]")

    def test_badge_appears_through_the_window_drift_pipeline(self, qtapp):
        window = MainWindow()
        window.on_baseline_saved(baseline_snapshot())
        report, current, heuristics = drift_check()
        window.on_drift_checked(report, current, heuristics)
        window.update_snapshots(
            cpu=CPUSnapshot(timestamp=1.0, aggregate_utilization_percent=12.4, cores=()),
            memory=None,
            processes=ProcessSnapshot(
                timestamp=1.0,
                processes=[
                    ProcessInfo(
                        pid=8150,
                        name="com.new.app",
                        uid=10003,
                        state="R",
                        cpu_percent=1.0,
                        memory_percent=1.0,
                        category=ProcessCategory.USER,
                    ),
                ],
            ),
            battery=None,
            network=None,
        )
        table = window.processes.findChild(QTableWidget)
        assert table.item(0, 4).text().startswith("[NEW] com.new.app")

    def test_new_baseline_clears_badges_through_the_window(self, qtapp):
        window = MainWindow()
        window.on_baseline_saved(baseline_snapshot())
        report, current, heuristics = drift_check()
        window.on_drift_checked(report, current, heuristics)
        assert window.processes._new_process_refs
        window.on_baseline_saved(current)
        assert not window.processes._new_process_refs


# ---------------------------------------------------------------------------
# Suspicious signals section
# ---------------------------------------------------------------------------


class TestSuspiciousSignals:
    def test_signals_rendered_with_severity_colors_and_full_reason(self, qtapp):
        panel = BaselinePanel()
        panel.set_baseline(baseline_snapshot())
        report, _current, _heuristics = drift_check()
        signals = (
            SuspiciousSignal(
                rule_id="RULE_A",
                severity="HIGH",
                entity="com.evil.app",
                reason="A new process is listening on a socket; this combination is worth reviewing.",
            ),
            SuspiciousSignal(
                rule_id="RULE_B",
                severity="MEDIUM",
                entity="com.medium.app",
                reason="A new unclassified package appeared alongside a new process.",
            ),
        )
        heuristics = HeuristicReport(
            evaluated_at=_AT,
            signals=signals,
            rules_applied=("RULE_A", "RULE_B", "RULE_C"),
        )
        panel.show_drift(report, heuristics)

        severities = panel.findChildren(QLabel)
        high = [l for l in severities if l.text() == "HIGH" and l.property("level") == "high"]
        medium = [l for l in severities if l.text() == "MEDIUM" and l.property("level") == "elevated"]
        assert high and medium
        assert _labels_with_text(panel, signals[0].reason)
        assert _labels_with_text(panel, signals[1].reason)
        assert _labels_with_text(panel, "com.evil.app")

    def test_empty_state_says_checked_and_nothing_found(self, qtapp):
        panel = BaselinePanel()
        panel.set_baseline(baseline_snapshot())
        report, _current, _heuristics = drift_check()
        panel.show_drift(
            report,
            HeuristicReport(
                evaluated_at=_AT,
                signals=(),
                rules_applied=("rule_a", "rule_b", "rule_c"),
            ),
        )
        assert _labels_with_text(panel, "No suspicious signals detected")
        assert _labels_with_text(panel, "3 rules checked")

    def test_not_checked_state_before_any_check(self, qtapp):
        panel = BaselinePanel()
        assert _labels_with_text(panel, "Not checked yet")


# ---------------------------------------------------------------------------
# Permissions section
# ---------------------------------------------------------------------------


def _inspector_with_resolved_app(qtapp) -> ProcessInspectorWidget:
    inspector = ProcessInspectorWidget()
    inspector.set_packages({"com.example.app"})
    inspector.set_snapshot(
        ProcessInspectionSnapshot(pid=1234, name="com.example.app"),
        None,
    )
    return inspector


class TestPermissionsTab:
    def test_audit_button_enabled_only_for_resolved_package(self, qtapp):
        inspector = ProcessInspectorWidget()
        inspector.set_packages({"com.example.app"})
        inspector.set_snapshot(ProcessInspectionSnapshot(pid=1, name="kernel_thread.gone"), None)
        button = _find_button(inspector, "Audit Permissions")
        assert not button.isEnabled()
        inspector.set_packages({"com.example.app"})
        inspector.set_snapshot(ProcessInspectionSnapshot(pid=2, name="com.example.app"), None)
        assert button.isEnabled()

    def test_unknown_state_renders_distinctly_from_granted_states(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        audit = permission_audit(parse_complete=True)
        inspector.show_permission_audit(audit)
        unknown = _labels_with_text(inspector, "Unknown")
        granted = _labels_with_text(inspector, "Granted")
        not_granted = _labels_with_text(inspector, "Not granted")
        assert len(unknown) == 1 and len(granted) == 1 and len(not_granted) == 1
        assert unknown[0].objectName() == "statusWarn"
        assert granted[0].objectName() == "statusConnected"
        assert not_granted[0].objectName() == "muted"

    def test_parse_complete_banner_shown_when_incomplete(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        inspector.show_permission_audit(permission_audit(parse_complete=False))
        banner = _labels_with_text(inspector, "Permission data may be incomplete")
        assert len(banner) == 1
        assert banner[0].isVisible()
        inspector.show_permission_audit(permission_audit(parse_complete=True))
        assert not banner[0].isVisible()

    def test_flag_description_rendered_verbatim_above_the_list(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        audit = permission_audit(parse_complete=True)
        inspector.show_permission_audit(audit)
        description = audit.combination_flags[0].description
        assert _labels_with_text(inspector, description)
        assert _labels_with_text(inspector, "SMS_ACCESSIBILITY_DEVICE_ADMIN")

    def test_groups_by_permission_type_with_counts(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        inspector.show_permission_audit(permission_audit(parse_complete=True))
        assert _labels_with_text(inspector, "Runtime permissions (2)")
        assert _labels_with_text(inspector, "Install permissions (1)")

    def test_stale_audit_discarded_after_selection_change(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        inspector.show_permission_audit(permission_audit(parse_complete=True))
        assert _labels_with_text(inspector, "Granted")
        inspector.set_packages({"com.other.app"})
        inspector.set_snapshot(ProcessInspectionSnapshot(pid=9, name="com.other.app"), None)
        qtapp.processEvents()
        inspector.show_permission_audit(permission_audit(parse_complete=True))
        assert not _labels_with_text(inspector, "Granted")
        assert _labels_with_text(
            inspector, "Run a permission audit to inspect package permissions."
        )

    def test_pre_audit_empty_state_invites_and_never_boxes(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        assert _labels_with_text(
            inspector, "Run a permission audit to inspect package permissions."
        )
        assert _labels_with_text(
            inspector, "Results will appear here after the audit completes."
        )
        inspector.show_permission_audit(permission_audit(parse_complete=True))
        assert not _labels_with_text(
            inspector, "Results will appear here after the audit completes."
        )

    def test_audit_with_no_permissions_shows_honest_empty_state(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        audit = PackagePermissionAudit(
            package_name="com.example.app",
            read_at=_AT,
            permissions=(),
            parse_complete=True,
            combination_flags=(),
        )
        inspector.show_permission_audit(audit)
        assert _labels_with_text(inspector, "No permissions were reported.")
        assert not _labels_with_text(
            inspector, "Results will appear here after the audit completes."
        )

    def test_audit_failure_shows_visible_status(self, qtapp):
        inspector = _inspector_with_resolved_app(qtapp)
        inspector._resolved_package = "com.example.app"
        inspector._refresh_permission_button()
        inspector.show_permission_audit_failed("com.example.app", "device offline")
        assert _labels_with_text(inspector, "Permission read failed: device offline")
        assert _find_button(inspector, "Audit Permissions").isEnabled()


# ---------------------------------------------------------------------------
# Workers: in-progress, success and failure without hanging
# ---------------------------------------------------------------------------


class StubRunner:
    """Minimal scripted CommandRunner stand-in."""

    def __init__(self, response: str = "", error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[list[str]] = []

    def shell(self, args, timeout=None):  # noqa: ARG002 - protocol signature
        self.calls.append(list(args))
        if self._error is not None:
            raise self._error
        return self._response


class _FakeBaselineWorker(BaselineWorker):
    """BaselineWorker whose device read is replaced by a fixture."""

    def __init__(self, result=current_snapshot(), error: Exception | None = None) -> None:
        super().__init__(connection=StubRunner(""))
        self._result = result
        self._error = error

    def build(self):
        if self._error is not None:
            raise self._error
        return self._result


class TestBaselineWorker:
    def test_save_publishes_snapshot(self, qtapp):
        result = current_snapshot()
        worker = _FakeBaselineWorker(result=result)
        saved: list = []
        worker.baseline_saved.connect(lambda snapshot: saved.append(snapshot))
        worker.request_save_baseline()
        assert saved and saved[0] is result
        assert not worker.is_busy()

    def test_save_failure_reported_without_crash_or_hang(self, qtapp):
        worker = _FakeBaselineWorker(error=ADBTimeoutError("dumpsys package", 5.0))
        failed: list = []
        worker.baseline_failed.connect(lambda message: failed.append(message))
        worker.request_save_baseline()
        assert len(failed) == 1
        assert "timed out" in failed[0]
        assert not worker.is_busy()

    def test_drift_check_publishes_report_current_and_heuristics(self, qtapp):
        result = current_snapshot()
        worker = _FakeBaselineWorker(result=result)
        reports: list = []
        worker.drift_checked.connect(
            lambda report, current, heuristics: reports.append((report, current, heuristics))
        )
        worker.request_drift_check(baseline_snapshot())
        assert len(reports) == 1
        report, current, heuristics = reports[0]
        assert len(report.events) == 1
        assert report.events[0].category == "process"
        assert current is result
        assert heuristics.rules_applied
        assert not worker.is_busy()

    def test_drift_failure_reported(self, qtapp):
        worker = _FakeBaselineWorker(error=ADBError("no device"))
        failed: list = []
        worker.drift_failed.connect(lambda message: failed.append(message))
        worker.request_drift_check(baseline_snapshot())
        assert failed and "no device" in failed[0]

    def test_export_writes_json_and_reports_success(self, qtapp, tmp_path):
        worker = BaselineWorker(connection=StubRunner(""))
        session = Session(
            baseline=baseline_snapshot(),
            current=current_snapshot(),
            drift_report=diff_snapshot(baseline_snapshot(), current_snapshot()),
        )
        results: list = []
        worker.export_completed.connect(
            lambda success, message: results.append((success, message))
        )
        out = tmp_path / "session.json"
        worker.request_export("json", str(out), session)
        assert results and results[0][0] is True
        assert out.exists()
        assert "session.json" in results[0][1]
        assert not worker.is_exporting()

    def test_export_failure_reported_never_silent(self, qtapp, tmp_path):
        worker = BaselineWorker(connection=StubRunner(""))
        session = Session(
            baseline=baseline_snapshot(),
            current=current_snapshot(),
            drift_report=diff_snapshot(baseline_snapshot(), current_snapshot()),
        )
        results: list = []
        worker.export_completed.connect(
            lambda success, message: results.append((success, message))
        )
        worker.request_export("json", str(tmp_path / "missing" / "x.json"), session)
        assert results and results[0][0] is False
        assert "failed" in results[0][1].lower()

    def test_export_unknown_format_rejected(self, qtapp, tmp_path):
        worker = BaselineWorker(connection=StubRunner(""))
        results: list = []
        worker.export_completed.connect(
            lambda success, message: results.append((success, message))
        )
        session = Session(baseline_snapshot(), current_snapshot(), diff_snapshot(baseline_snapshot(), current_snapshot()))
        worker.request_export("yaml", str(tmp_path / "s.yaml"), session)
        assert results and results[0][0] is False


class TestPermissionWorker:
    def test_audit_reads_and_publishes(self, qtapp):
        dump = (
            "Package [com.example.app] (abc):\n"
            "install permissions:\n"
            "android.permission.INTERNET: granted=true\n"
        )
        runner = StubRunner(response=dump)
        worker = PermissionWorker(connection=runner)
        audit: list = []
        worker.audit_ready.connect(lambda result: audit.append(result))
        worker.request_audit("com.example.app")
        assert runner.calls == [["dumpsys", "package", "com.example.app"]]
        assert len(audit) == 1
        assert audit[0].package_name == "com.example.app"
        assert audit[0].parse_complete is True
        assert not worker.is_busy()

    def test_audit_failure_reported(self, qtapp):
        worker = PermissionWorker(connection=StubRunner(error=ADBError("device offline")))
        failed: list = []
        worker.audit_failed.connect(lambda package, message: failed.append((package, message)))
        worker.request_audit("com.example.app")
        assert failed == [("com.example.app", "device offline")]
        assert not worker.is_busy()


# ---------------------------------------------------------------------------
# Inspector network-socket badges
# ---------------------------------------------------------------------------


class TestNetworkSocketBadges:
    def test_new_socket_row_badged_only_when_owned_by_this_process(self, qtapp):
        from android_task_manager.baseline import SocketIdentity
        from android_task_manager.network_investigation.models import (
            NetworkInvestigationSnapshot,
            SocketInfo,
        )

        inspector = ProcessInspectorWidget()
        inspector.set_snapshot(
            ProcessInspectionSnapshot(pid=7, name="com.owned.app", uid=1001),
            NetworkInvestigationSnapshot(
                timestamp=1.0,
                sockets=(
                    SocketInfo(
                        protocol="tcp",
                        family="ipv4",
                        local_address="0.0.0.0",
                        local_port=4444,
                        state="LISTEN",
                        uid=1001,
                    ),
                    SocketInfo(
                        protocol="tcp",
                        family="ipv4",
                        local_address="0.0.0.0",
                        local_port=80,
                        state="LISTEN",
                        uid=1001,
                    ),
                ),
                source_available=True,
                uid_packages={1001: ("com.owned.app",)},
            ),
        )
        new_sockets = frozenset(
            {
                SocketIdentity(protocol="tcp", local_address="0.0.0.0", local_port=4444, uid=1001)
            }
        )
        inspector.set_new_socket_identities(new_sockets)
        table = inspector.findChild(QTableWidget)
        by_local = {
            table.item(row, 1).text(): table.item(row, 0).text()
            for row in range(table.rowCount())
        }
        assert by_local["0.0.0.0:4444"].startswith("[NEW] TCP IPV4")
        assert by_local["0.0.0.0:80"] == "TCP IPV4"

        inspector.set_new_socket_identities(frozenset())
        for row in range(table.rowCount()):
            assert not table.item(row, 0).text().startswith("[NEW]")


class TestExportCancellation:
    def test_cancel_reports_status_instead_of_silent_noop(self, qtapp, monkeypatch):
        window = MainWindow()
        window.on_baseline_saved(baseline_snapshot())
        report, current, heuristics = drift_check()
        window.on_drift_checked(report, current, heuristics)

        import PySide6.QtWidgets as qt_widgets

        sent: list = []
        window.baseline_export_requested.connect(lambda *a: sent.append(a))

        monkeypatch.setattr(
            qt_widgets.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: ("", "")),
        )
        window._on_export_requested("json")
        assert _labels_with_text(window.security, "Export cancelled.")
        assert not sent

        monkeypatch.setattr(
            qt_widgets.QFileDialog,
            "getSaveFileName",
            staticmethod(lambda *a, **k: (r"C:\nonsense\session.json", "")),
        )
        window._on_export_requested("json")
        assert sent
        kind, path, session = sent[0]
        assert kind == "json"
        assert session.baseline == window._baseline
        assert session.drift_report == window._drift_report
        status = _labels_with_text(window.security, "Exporting…")
        assert status