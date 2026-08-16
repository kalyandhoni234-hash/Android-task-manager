"""Headless GUI tests for the Device Report Export feature area (D3).

Offscreen Qt platform; never touches a device or ADB. Covers: the
DevicePage export button laws, the MainWindow export flow (dialog,
cancel, payload assembly), the worker (success/write failure/duplicate
drop), and the wiring. Also re-verifies that the incident export worker
still functions alongside the new one.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.device.models import DeviceInformation
from android_task_manager.device_report import DeviceReportPayload
from android_task_manager.device_report.render import device_report_filename
from android_task_manager.gui.device_page import DevicePage
from android_task_manager.gui.device_report_worker import DeviceReportWorker
from android_task_manager.gui.main_window import MainWindow, wire_device_report
from android_task_manager.gui.monitor import ConnectionState
from android_task_manager.gui.widgets.device_widget import DeviceWidget

_SERIAL = "R58M29ABCDE"


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


def _payload(serial: str | None = _SERIAL) -> DeviceReportPayload:
    return DeviceReportPayload(
        info=DeviceInformation(manufacturer="vivo", model="V2026"),
        battery=BatterySnapshot(
            timestamp=1.0,
            level_percent=50.0,
            scale=100,
            voltage_mv=None,
            temperature_c=None,
            status=BatteryStatus.UNKNOWN,
            status_raw=None,
            health=BatteryHealth.UNKNOWN,
            health_raw=None,
            present=None,
            ac_powered=None,
            usb_powered=None,
            wireless_powered=None,
            technology="",
            charge_counter=None,
        ),
        memory=None,
        cpu=None,
        diagnostics=None,
        device_serial=serial,
        generated_at=datetime(2026, 8, 16, 12, 30, 0),
    )


def _find_button(widget, text: str):
    from PySide6.QtWidgets import QPushButton

    return next(
        (b for b in widget.findChildren(QPushButton) if b.text() == text), None
    )


# ---------------------------------------------------------------------------
# DevicePage export button laws
# ---------------------------------------------------------------------------


def test_export_button_disabled_until_connected(qtapp):
    page = DevicePage(DeviceWidget())
    button = _find_button(page, "Export Device Report")
    assert button is not None
    assert not button.isEnabled()
    page.refresh(
        DeviceInformation(model="V2026"), None, None, None, ConnectionState.DISCONNECTED
    )
    assert not button.isEnabled()
    page.refresh(
        DeviceInformation(model="V2026"), None, None, None, ConnectionState.CONNECTED
    )
    assert button.isEnabled()


def test_export_button_disabled_while_busy_and_restored(qtapp):
    page = DevicePage(DeviceWidget())
    page.set_export_available(True)
    page.set_export_busy(True)
    assert not _find_button(page, "Export Device Report").isEnabled()
    page.show_export_result(True, "Exported device report to C:/r.json.")
    assert _find_button(page, "Export Device Report").isEnabled()
    assert "C:/r.json" in page._export_status.text()


def test_export_button_emits_request(qtapp):
    page = DevicePage(DeviceWidget())
    requested = []
    page.export_requested.connect(lambda: requested.append(True))
    page.set_export_available(True)
    _find_button(page, "Export Device Report").click()
    assert requested


def test_export_status_cleared_on_disconnect(qtapp):
    page = DevicePage(DeviceWidget())
    page.set_export_available(True)
    page.show_export_result(False, "Export failed: nope")
    page.refresh(None, None, None, None, ConnectionState.DISCONNECTED)
    assert page._export_status.text() == ""
    assert not _find_button(page, "Export Device Report").isEnabled()


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def test_worker_writes_json(qtapp, tmp_path):
    worker = DeviceReportWorker()
    path = tmp_path / "report.json"
    message = worker.export_report(_payload(), path)
    assert path.read_text(encoding="utf-8").startswith("{")
    assert json.loads(path.read_text(encoding="utf-8"))["report_type"] == "device_report"
    assert "Exported device report" in message


def test_worker_reports_write_failures(qtapp, tmp_path):
    worker = DeviceReportWorker()
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    missing = tmp_path / "no" / "such" / "dir" / "report.json"
    worker.request_export(str(missing), _payload())
    assert results and not results[0][0]
    assert "Export failed" in results[0][1]
    assert not worker.is_exporting()


def test_worker_drops_duplicate_exports_while_busy(qtapp, tmp_path):
    worker = DeviceReportWorker()
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    worker._export_busy = True
    worker.request_export(str(tmp_path / "a.json"), _payload())
    assert results == []
    worker._export_busy = False


def test_worker_rejects_invalid_payload(qtapp, tmp_path):
    worker = DeviceReportWorker()
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    worker.request_export(str(tmp_path / "a.json"), "not a payload")
    assert results and not results[0][0]
    assert "cancelled" in results[0][1]


def test_worker_needs_no_adb_or_connection(qtapp, tmp_path):
    # Constructing and using the worker never requires a device: no
    # connection object exists anywhere in this flow.
    worker = DeviceReportWorker()
    assert not hasattr(worker, "_connection")
    path = tmp_path / "report.json"
    worker.request_export(str(path), _payload())
    assert path.exists()


# ---------------------------------------------------------------------------
# MainWindow export flow
# ---------------------------------------------------------------------------


def test_main_window_export_request_flow(qtapp, tmp_path, monkeypatch):
    window = MainWindow()
    window._device_serial = _SERIAL
    window.device_information = DeviceInformation(manufacturer="vivo", model="V2026")
    emitted = []
    window.device_report_export_requested.connect(
        lambda path, payload: emitted.append((path, payload))
    )
    target = str(tmp_path / "flow.json")

    import PySide6.QtWidgets as qt_widgets

    monkeypatch.setattr(
        qt_widgets.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (target, "JSON file (*.json)")),
    )
    window._on_device_report_export_requested()
    assert emitted and emitted[0][0] == target
    assert emitted[0][1].device_serial == _SERIAL
    assert emitted[0][1].info is window.device_information
    assert window.device_page._exporting
    window.close()


def test_main_window_export_cancel_is_clean_noop(qtapp, monkeypatch):
    window = MainWindow()
    window._device_serial = _SERIAL
    emitted = []
    window.device_report_export_requested.connect(
        lambda path, payload: emitted.append((path, payload))
    )
    import PySide6.QtWidgets as qt_widgets

    monkeypatch.setattr(
        qt_widgets.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: ("", "")),
    )
    window._on_device_report_export_requested()
    assert emitted == []
    assert not window.device_page._exporting
    window.close()


def test_main_window_export_without_device_is_honest(qtapp):
    window = MainWindow()
    emitted = []
    window.device_report_export_requested.connect(
        lambda path, payload: emitted.append((path, payload))
    )
    window._on_device_report_export_requested()
    assert emitted == []
    assert "No device connected" in window.device_page._export_status.text()
    window.close()


def test_wire_device_report_delivers_exports(qtapp, tmp_path):
    window = MainWindow()
    worker = DeviceReportWorker()
    wire_device_report(window, worker)
    results = []
    worker.export_completed.connect(lambda ok, msg: results.append((ok, msg)))
    target = tmp_path / "wired.json"
    window.device_report_export_requested.emit(str(target), _payload())
    assert target.exists()
    assert results and results[0][0]
    assert json.loads(target.read_text(encoding="utf-8"))["device_serial"] == _SERIAL
    window.close()


def test_default_filename_from_window_uses_serial(qtapp):
    # The suggested name comes from the serial + local time (deterministic
    # shape), so the exported artifact is identifiable per device.
    window = MainWindow()
    name = device_report_filename(_SERIAL, datetime(2026, 8, 16, 12, 30, 0))
    assert name == "device-report-R58M29ABCDE-2026-08-16_123000.json"
    window.close()


# ---------------------------------------------------------------------------
# Coexistence with the incident export worker (regression)
# ---------------------------------------------------------------------------


def test_incident_export_still_works_alongside(qtapp, tmp_path):
    from android_task_manager.gui.incident_worker import IncidentWorker
    from android_task_manager.incident.builder import build_incident_report
    from tests import incident_fixtures as fx

    worker = IncidentWorker()
    report = build_incident_report(**fx.ALL_SCENARIOS["g"]())
    path = tmp_path / "incident.json"
    message = worker.export_report(report, "json", path)
    assert path.read_text(encoding="utf-8").startswith("{")
    assert "JSON" in message
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2