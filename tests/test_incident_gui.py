"""Headless GUI tests for the Incident Reporting feature area.

Offscreen Qt platform; never touches a device. The report is generated
from in-memory fixture data (the same scenarios the core tests use).
Covers: panel button laws, generation from the MainWindow, honest reset on
a new baseline, audit collection bounds, the viewer dialog, the export
worker (JSON/HTML/PDF, duplicate-drop, error reporting), and the wiring.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.gui.incident_dialog import IncidentDialog
from android_task_manager.gui.incident_worker import IncidentWorker
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.widgets.incident_panel import IncidentPanel
from android_task_manager.incident.builder import build_incident_report
from android_task_manager.incident.models import SOURCE_GUI
from tests import incident_fixtures as fx


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _report():
    return build_incident_report(**fx.ALL_SCENARIOS["g"]())


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


def test_panel_initial_state_is_honest(qtapp) -> None:
    panel = IncidentPanel()
    assert "No report generated yet" in panel._report_label.text()
    assert not panel._generate_btn.isEnabled()
    assert not panel._view_btn.isEnabled()
    assert not panel._json_btn.isEnabled()
    assert not panel._html_btn.isEnabled()
    assert not panel._pdf_btn.isEnabled()


def test_panel_generate_requires_session_data(qtapp) -> None:
    panel = IncidentPanel()
    panel.set_generation_available(True)
    assert panel._generate_btn.isEnabled()
    assert not panel._view_btn.isEnabled()
    panel.set_generation_available(False)
    assert not panel._generate_btn.isEnabled()


def test_panel_adopts_report_and_enables_exports(qtapp) -> None:
    panel = IncidentPanel()
    report = _report()
    panel.set_generation_available(True)
    panel.set_report(report)
    assert panel._view_btn.isEnabled()
    assert panel._json_btn.isEnabled()
    assert panel._html_btn.isEnabled()
    assert panel._pdf_btn.isEnabled()
    label = panel._report_label.text()
    assert report.metadata.report_id in label
    assert report.severity_summary.assessment in label
    assert "2 MEDIUM" in label


def test_panel_clearing_report_resets_buttons(qtapp) -> None:
    panel = IncidentPanel()
    panel.set_report(_report())
    panel.set_report(None)
    assert not panel._view_btn.isEnabled()
    assert not panel._json_btn.isEnabled()


def test_panel_busy_states_disable_everything(qtapp) -> None:
    panel = IncidentPanel()
    panel.set_generation_available(True)
    panel.set_report(_report())
    panel.set_export_busy(True)
    for button in (
        panel._generate_btn,
        panel._view_btn,
        panel._json_btn,
        panel._html_btn,
        panel._pdf_btn,
    ):
        assert not button.isEnabled()
    panel.set_export_busy(False)
    assert panel._json_btn.isEnabled()


def test_panel_click_emits_typed_requests(qtapp) -> None:
    panel = IncidentPanel()
    generated, viewed, exports = [], [], []
    panel.generate_requested.connect(lambda: generated.append(True))
    panel.view_requested.connect(lambda: viewed.append(True))
    panel.export_requested.connect(lambda kind: exports.append(kind))
    panel.set_generation_available(True)
    panel._generate_btn.click()
    panel.set_report(_report())
    panel._view_btn.click()
    panel._json_btn.click()
    panel._pdf_btn.click()
    assert generated and viewed and exports == ["json", "pdf"]


# ---------------------------------------------------------------------------
# MainWindow generation + state
# ---------------------------------------------------------------------------


def test_main_window_generates_report_from_session_data(qtapp) -> None:
    window = MainWindow()
    inputs = fx.scenario_g_correlated()
    window._baseline = inputs["session"].baseline
    window._current_snapshot = inputs["session"].current
    window._drift_report = inputs["session"].drift_report
    window._heuristics = inputs["heuristics"]
    window._permission_audits = []
    window._latest_network_investigation = inputs["network_investigation"]
    window._latest_processes = inputs["process_snapshot"]
    window._device_label = "Pixel Test"
    window._android_version = "15"

    window._on_incident_generate_requested()

    report = window._incident_report
    assert report is not None
    assert report.metadata.source == SOURCE_GUI
    assert report.metadata.report_id.startswith("ATM-")
    assert report.device.label == "Pixel Test"
    assert report.device.android_version == "15"
    assert report.severity_summary.high == 1
    window.close()


def test_main_window_generation_without_session_is_noop(qtapp) -> None:
    window = MainWindow()
    window._on_incident_generate_requested()
    assert window._incident_report is None
    window.close()


def test_new_baseline_resets_incident_state(qtapp) -> None:
    window = MainWindow()
    inputs = fx.scenario_g_correlated()
    window._baseline = inputs["session"].baseline
    window._current_snapshot = inputs["session"].current
    window._drift_report = inputs["session"].drift_report
    window._heuristics = inputs["heuristics"]
    window._on_incident_generate_requested()
    assert window._incident_report is not None
    assert window.incident._report is not None

    window.on_baseline_saved(inputs["session"].baseline)

    assert window._heuristics is None
    assert window._permission_audits == []
    assert window._incident_report is None
    assert window.incident._report is None
    assert not window.incident._generate_btn.isEnabled()
    window.close()


def test_drift_check_enables_generation_and_stores_heuristics(qtapp) -> None:
    window = MainWindow()
    inputs = fx.scenario_g_correlated()
    window.on_drift_checked(
        inputs["session"].drift_report,
        inputs["session"].current,
        inputs["heuristics"],
    )
    assert window._heuristics is not None
    assert window.incident._generation_available
    assert window.incident._generate_btn.isEnabled()
    window.close()


def test_permission_audits_collected_with_bound(qtapp) -> None:
    window = MainWindow()
    audits = [fx.audit(f"com.example.app{i}") for i in range(25)]
    for audit in audits:
        window.on_permission_audit_ready(audit)
    assert len(window._permission_audits) == 20
    assert window._permission_audits[0].package_name == "com.example.app5"
    window.close()


# ---------------------------------------------------------------------------
# Viewer dialog
# ---------------------------------------------------------------------------


def test_dialog_renders_report_and_emits_exports(qtapp) -> None:
    report = _report()
    dialog = IncidentDialog()
    dialog.show_report(report)
    assert report.metadata.report_id in dialog._view.toHtml()
    assert "ANDROID SECURITY INVESTIGATION REPORT" in dialog._view.toHtml()
    exports = []
    dialog.export_requested.connect(lambda kind: exports.append(kind))
    dialog._json_btn.click()
    dialog._pdf_btn.click()
    assert exports == ["json", "pdf"]
    dialog.close()


def test_dialog_buttons_follow_state(qtapp) -> None:
    dialog = IncidentDialog()
    assert not dialog._json_btn.isEnabled()
    dialog.show_report(_report())
    assert dialog._json_btn.isEnabled()
    dialog.set_export_busy(True)
    assert not dialog._json_btn.isEnabled()
    dialog.show_export_result(True, "ok")
    assert dialog._json_btn.isEnabled()
    assert dialog._status.text() == "ok"
    dialog.close()


# ---------------------------------------------------------------------------
# Export worker
# ---------------------------------------------------------------------------


def test_worker_writes_json_html_pdf(qtapp, tmp_path) -> None:
    worker = IncidentWorker()
    report = _report()

    json_path = tmp_path / "r.json"
    message = worker.export_report(report, "json", json_path)
    assert json_path.read_text(encoding="utf-8").startswith("{")
    assert "JSON" in message

    html_path = tmp_path / "r.html"
    worker.export_report(report, "html", html_path)
    assert "ANDROID SECURITY INVESTIGATION REPORT" in html_path.read_text(encoding="utf-8")

    pdf_path = tmp_path / "r.pdf"
    worker.export_report(report, "pdf", pdf_path)
    header = pdf_path.read_bytes()[:5]
    assert header == b"%PDF-"


def test_worker_rejects_unknown_format(qtapp, tmp_path) -> None:
    worker = IncidentWorker()
    with pytest.raises(ValueError):
        worker.export_report(_report(), "txt", tmp_path / "r.txt")


def test_worker_reports_write_failures(qtapp, tmp_path) -> None:
    worker = IncidentWorker()
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    missing = tmp_path / "no" / "such" / "dir" / "r.json"
    worker.request_export("json", str(missing), _report())
    assert results and not results[0][0]
    assert "Export failed" in results[0][1]
    assert not worker.is_exporting()


def test_worker_drops_duplicate_exports_while_busy(qtapp, tmp_path) -> None:
    worker = IncidentWorker()
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    # Without a real thread the first call completes synchronously, so mark
    # the worker busy explicitly to simulate an in-flight export.
    worker._export_busy = True
    worker.request_export("json", str(tmp_path / "a.json"), _report())
    assert results == []
    worker._export_busy = False


def test_wire_incident_delivers_exports(qtapp, tmp_path) -> None:
    window = MainWindow()
    worker = IncidentWorker()
    from android_task_manager.gui.main_window import wire_incident

    wire_incident(window, worker)
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    report = _report()
    target = tmp_path / "wired.json"
    window.incident_export_requested.emit("json", str(target), report)
    assert target.exists()
    assert results and results[0][0]
    window.close()


def test_main_window_export_request_flow(qtapp, tmp_path, monkeypatch) -> None:
    window = MainWindow()
    report = _report()
    window._incident_report = report
    emitted = []
    window.incident_export_requested.connect(
        lambda kind, path, rep: emitted.append((kind, path, rep))
    )
    target = str(tmp_path / "flow.json")

    import PySide6.QtWidgets as qt_widgets

    monkeypatch.setattr(
        qt_widgets.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (target, "JSON file (*.json)")),
    )
    window._on_incident_export_requested("json")
    assert emitted and emitted[0][0] == "json"
    assert emitted[0][1] == target
    assert emitted[0][2] is report
    assert window.incident._exporting
    window.close()