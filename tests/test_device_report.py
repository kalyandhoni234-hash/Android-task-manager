"""Core tests for the device report export layer (D3).

Pure serialization tests — no GUI, no device, no ADB. Verifies the 14
D3 requirements at the artifact level: determinism, schema/content,
diagnostic inclusion, ordering, privacy/redaction, integrity, and
round-trip parsing. All fixtures are in-memory; nothing touches disk
except the explicit write tests (``tmp_path``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from android_task_manager.battery.models import (
    BatteryHealth,
    BatterySnapshot,
    BatteryStatus,
)
from android_task_manager.cpu.models import CPUCore, CPUSnapshot
from android_task_manager.device.models import (
    DeviceInformation,
    NetworkInterfaceInfo,
    StorageInfo,
)
from android_task_manager.device_report import (
    SCHEMA_VERSION,
    DeviceReportPayload,
    device_report_filename,
    device_report_json,
    payload_to_dict,
    write_device_report,
)
from android_task_manager.diagnostics.models import (
    DiagnosticCategory,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticSeverity,
)
from android_task_manager.memory.models import MemorySnapshot

_GENERATED_AT = datetime(2026, 8, 16, 12, 30, 0)
_SERIAL = "R58M29ABCDE"


def _info() -> DeviceInformation:
    return DeviceInformation(
        manufacturer="vivo",
        brand="vivo",
        model="V2026",
        android_version="11",
        api_level="30",
        android_id="secret-android-id",
        wifi_mac="aa:bb:cc:dd:ee:ff",
        bluetooth_mac="11:22:33:44:55:66",
        wifi_bssid="aa:bb:cc:dd:ee:01",
        storage_filesystem="f2fs",
        storage=StorageInfo(
            mount="/data", total_kb=1000000, used_kb=900000, available_kb=100000
        ),
        network_interfaces=(
            NetworkInterfaceInfo(
                name="wlan0",
                interface_type="Wi-Fi",
                is_up=True,
                is_default_route=True,
                mac_address="aa:bb:cc:dd:ee:ff",
                ipv4_addresses=("192.168.50.10/24",),
                ipv6_addresses=(),
            ),
        ),
    )


def _battery() -> BatterySnapshot:
    return BatterySnapshot(
        timestamp=123.0,
        level_percent=87.5,
        scale=100,
        voltage_mv=4100,
        temperature_c=31.2,
        status=BatteryStatus.CHARGING,
        status_raw=2,
        health=BatteryHealth.GOOD,
        health_raw=2,
        present=True,
        ac_powered=True,
        usb_powered=False,
        wireless_powered=False,
        technology="Li-poly",
        charge_counter=4123000,
    )


def _memory() -> MemorySnapshot:
    return MemorySnapshot(
        timestamp=124.0,
        total_kb=7716096,
        free_kb=1200000,
        available_kb=3200000,
        buffers_kb=200000,
        cached_kb=1500000,
        swap_cached_kb=0,
    )


def _cpu() -> CPUSnapshot:
    return CPUSnapshot(
        timestamp=125.0,
        aggregate_utilization_percent=12.5,
        cores=(
            CPUCore(core_id=0, utilization_percent=10.0, frequency_khz=1800000, frequency_available=True),
            CPUCore(core_id=1, utilization_percent=15.0, frequency_khz=1200000, frequency_available=True),
        ),
    )


def _finding(
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
    title: str = "Storage nearly full",
) -> DiagnosticFinding:
    return DiagnosticFinding(
        severity=severity,
        category=DiagnosticCategory.STORAGE,
        title=title,
        what="The internal volume is nearly full.",
        why="Usage crossed the 80% threshold.",
        evidence="/data usage: 90%",
        recommended_action="Free up space.",
    )


def _diagnostics() -> DiagnosticReport:
    return DiagnosticReport(
        findings=(
            _finding(severity=DiagnosticSeverity.CRITICAL, title="First"),
            _finding(severity=DiagnosticSeverity.INFO, title="Second"),
        )
    )


def _payload(
    info: DeviceInformation | None = None,
    battery: BatterySnapshot | None = None,
    memory: MemorySnapshot | None = None,
    cpu: CPUSnapshot | None = None,
    diagnostics: DiagnosticReport | None = None,
    serial: str | None = _SERIAL,
) -> DeviceReportPayload:
    return DeviceReportPayload(
        info=info,
        battery=battery,
        memory=memory,
        cpu=cpu,
        diagnostics=diagnostics,
        device_serial=serial,
        generated_at=_GENERATED_AT,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_exports_are_byte_identical():
    first = device_report_json(_payload(info=_info()))
    second = device_report_json(_payload(info=_info()))
    assert first == second


def test_export_is_byte_identical_after_file_round_trip(tmp_path):
    payload = _payload(info=_info(), battery=_battery())
    path = tmp_path / "report.json"
    write_device_report(payload, path)
    assert path.read_text(encoding="utf-8") == device_report_json(payload)


# ---------------------------------------------------------------------------
# Schema / content
# ---------------------------------------------------------------------------


def test_metadata_markers_present():
    data = payload_to_dict(_payload())
    assert data["report_type"] == "device_report"
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["generated_at"] == _GENERATED_AT.isoformat()
    assert isinstance(data["application_version"], str)
    assert data["application_version"]
    assert data["device_serial"] == _SERIAL


def test_device_sections_present_with_all_groups():
    data = payload_to_dict(_payload(info=_info()))
    device = data["device"]
    for section in (
        "identity",
        "software",
        "cpu_hardware",
        "gpu",
        "display",
        "storage",
        "network",
        "security",
    ):
        assert section in device
    assert device["identity"]["manufacturer"] == "vivo"
    assert device["storage"]["filesystem"] == "f2fs"
    assert device["storage"]["internal_volume"]["used_percent"] == 90.0
    assert device["network"]["interfaces"][0]["name"] == "wlan0"


def test_live_sections_present():
    data = payload_to_dict(_payload(battery=_battery(), memory=_memory(), cpu=_cpu()))
    assert data["battery"]["level_percent"] == 87.5
    assert data["battery"]["status"] == "Charging"
    assert data["battery"]["status_raw"] == 2
    assert data["battery"]["health"] == "Good"
    assert data["memory"]["used_kb"] == 7716096 - 3200000
    assert data["cpu"]["aggregate_utilization_percent"] == 12.5
    assert data["cpu"]["cores"][0]["core_id"] == 0


def test_null_sections_are_explicit_nulls():
    data = payload_to_dict(_payload())
    assert data["device"] is None
    assert data["battery"] is None
    assert data["memory"] is None
    assert data["cpu"] is None
    assert data["diagnostics"] is None


# ---------------------------------------------------------------------------
# Diagnostics inclusion (verbatim, report order)
# ---------------------------------------------------------------------------


def test_diagnostics_findings_verbatim_in_report_order():
    data = payload_to_dict(_payload(diagnostics=_diagnostics()))
    findings = data["diagnostics"]
    assert [f["title"] for f in findings] == ["First", "Second"]
    first = findings[0]
    assert first["severity"] == "critical"
    assert first["category"] == "storage"
    assert first["what"] == "The internal volume is nearly full."
    assert first["why"] == "Usage crossed the 80% threshold."
    assert first["evidence"] == "/data usage: 90%"
    assert first["recommended_action"] == "Free up space."


def test_empty_diagnostics_distinct_from_no_evaluation():
    empty = payload_to_dict(_payload(diagnostics=DiagnosticReport(findings=())))
    assert empty["diagnostics"] == []
    none_report = payload_to_dict(_payload(diagnostics=None))
    assert none_report["diagnostics"] is None


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_payload_fixed_key_order():
    data = payload_to_dict(_payload(info=_info()))
    assert list(data) == [
        "report_type",
        "schema_version",
        "generated_at",
        "application_version",
        "device_serial",
        "device",
        "battery",
        "memory",
        "cpu",
        "diagnostics",
        "integrity",
    ]


# ---------------------------------------------------------------------------
# Privacy / redaction
# ---------------------------------------------------------------------------


def test_sensitive_identifiers_never_serialized():
    data = payload_to_dict(_payload(info=_info()))
    text = json.dumps(data)
    for secret in (
        "secret-android-id",
        "aa:bb:cc:dd:ee:ff",
        "11:22:33:44:55:66",
        "aa:bb:cc:dd:ee:01",
    ):
        assert secret not in text


def test_per_interface_mac_addresses_excluded():
    data = payload_to_dict(_payload(info=_info()))
    interface = data["device"]["network"]["interfaces"][0]
    assert "mac_address" not in interface
    assert "aa:bb:cc:dd:ee:ff" not in json.dumps(interface)


def test_serial_stays_available_for_artifact_identity():
    # The serial is the same value baseline session exports already store;
    # it is excluded from logs by the existing secret registry instead.
    data = payload_to_dict(_payload(serial="R58M29ABCDE"))
    assert data["device_serial"] == "R58M29ABCDE"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_integrity_digest_covers_canonical_payload():
    data = payload_to_dict(_payload(info=_info(), battery=_battery()))
    digest = data["integrity"]
    assert digest["algorithm"] == "sha256"
    body = {key: value for key, value in data.items() if key != "integrity"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert digest["value"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_integrity_changes_when_payload_changes():
    plain = payload_to_dict(_payload(battery=None))
    changed = payload_to_dict(_payload(battery=_battery()))
    assert plain["integrity"]["value"] != changed["integrity"]["value"]


def test_digest_ignores_whitespace_layout():
    # The digest is computed over the compact canonical form, so the
    # indented on-disk layout never affects it.
    data = payload_to_dict(_payload(info=_info()))
    from android_task_manager.device_report.render import _integrity_digest

    body = {key: value for key, value in data.items() if key != "integrity"}
    assert data["integrity"]["value"] == _integrity_digest(body)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_written_file_parses_back_to_identical_payload(tmp_path):
    payload = _payload(info=_info(), battery=_battery(), memory=_memory(), cpu=_cpu())
    path = tmp_path / "report.json"
    write_device_report(payload, path)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed == payload_to_dict(payload)


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------


def test_filename_is_deterministic_and_filesystem_safe():
    name = device_report_filename(_SERIAL, _GENERATED_AT)
    assert name == "device-report-R58M29ABCDE-2026-08-16_123000.json"
    assert all(c.isalnum() or c in "._-" for c in name)


def test_filename_sanitizes_hostile_serials():
    name = device_report_filename("my;device/serial:1", _GENERATED_AT)
    assert ";" not in name
    assert "/" not in name
    assert ":" not in name
    assert name.startswith("device-report-")


def test_filename_fallback_without_serial():
    name = device_report_filename(None, _GENERATED_AT)
    assert name.startswith("device-report-device-")


# ---------------------------------------------------------------------------
# Write behavior
# ---------------------------------------------------------------------------


def test_write_failure_raises(tmp_path):
    payload = _payload()
    missing = tmp_path / "no" / "such" / "dir" / "report.json"
    try:
        write_device_report(payload, missing)
        raise AssertionError("expected OSError")
    except OSError:
        pass


def test_no_adb_anywhere_in_the_artifact_path():
    # The report layer only touches models + stdlib: constructing a payload
    # and rendering it must work with zero ADB/device involvement.
    import android_task_manager.device_report.render as module

    assert "adb" not in module.__name__
    assert "subprocess" not in dir(module)
    assert "network" not in {name for name in dir(module) if name.islower()}