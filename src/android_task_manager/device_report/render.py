"""Device report export: a deterministic, evidence-backed local JSON artifact.

The device report captures the structured identity snapshot of the connected
device (``DeviceInformation``), the latest live battery/memory/CPU snapshots,
and the diagnostics findings (verbatim, in report order) at the moment the
user asks for an export. It is a point-in-time artifact, not a session
recording: every value is the same data the GUI already renders, serialized
with no additional ADB traffic.

Design rules (mirroring ``incident/renderers.py``):

* **Deterministic.** ``payload_to_dict`` emits a fixed key order, tuples and
  cores serialize in their canonical (sorted-by-id) order, and
  ``device_report_json`` uses ``sort_keys=True`` with a fixed indent — the
  same inputs always produce a byte-identical file.
* **Integrity.** The artifact carries a SHA-256 of its canonical payload
  (stdlib ``hashlib`` only). The digest covers the compact, key-sorted JSON
  of everything except the ``integrity`` key itself.
* **Privacy.** The report is local-only and carries the device serial (the
  same value the baseline session export already stores), but it never
  contains the identifiers the incident report also excludes: ``android_id``,
  the Wi-Fi/Bluetooth MAC addresses, the Wi-Fi BSSID and per-interface MAC
  addresses are not serialized at all.
* **Honest ``None``.** Unavailable values serialize as JSON ``null`` and
  deserialize back to ``None`` — never ``0``, never a fabricated value.
* **No network.** Rendering and writing are pure local operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..battery.models import BatterySnapshot
from ..cpu.models import CPUSnapshot
from ..device.models import DeviceInformation
from ..diagnostics.models import DiagnosticReport
from ..memory.models import MemorySnapshot

#: Report schema version. Bump only when the on-disk shape changes; the
#: value is embedded in every artifact so consumers can detect the change.
SCHEMA_VERSION = 1

#: The canonical report type marker.
REPORT_TYPE = "device_report"

#: ``DeviceInformation`` fields that must never reach an artifact.
_SENSITIVE_FIELDS = frozenset(
    {
        "android_id",
        "wifi_mac",
        "bluetooth_mac",
        "wifi_bssid",
    }
)

_FILENAME_STAMP = "%Y-%m-%d_%H%M%S"
_SERIAL_MAX_LEN = 40


@dataclass(frozen=True)
class DeviceReportPayload:
    """Everything one device report contains, as typed objects.

    Every field is optional: an export taken before the first battery sample
    (or with no diagnostics evaluation yet) still produces a complete,
    valid artifact with ``null`` sections. ``device_serial`` is the ADB
    serial of the connected device (from the monitor's connection state).
    """

    info: DeviceInformation | None
    battery: BatterySnapshot | None
    memory: MemorySnapshot | None
    cpu: CPUSnapshot | None
    diagnostics: DiagnosticReport | None
    device_serial: str | None
    generated_at: datetime


# ---------------------------------------------------------------------------
# Deterministic section builders
# ---------------------------------------------------------------------------


def _opt(value: Any) -> Any:
    """Keep values JSON-ready; pass ``None`` through untouched."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def _section(info: DeviceInformation, fields: list[str]) -> dict[str, Any]:
    """Serialize one explicit field selection of ``DeviceInformation``.

    The selection is explicit so a future model extension can never
    accidentally leak a sensitive identifier into the artifact.
    """
    return {name: _opt(getattr(info, name)) for name in fields}


def _info_section(info: DeviceInformation) -> dict[str, Any]:
    """The device identity sections, excluding all sensitive identifiers."""
    storage: dict[str, Any] | None = None
    if info.storage is not None:
        storage = {
            "mount": info.storage.mount,
            "total_kb": info.storage.total_kb,
            "used_kb": info.storage.used_kb,
            "available_kb": info.storage.available_kb,
            "used_percent": info.storage.used_percent,
        }
    interfaces: list[dict[str, Any]] | None = None
    if info.network_interfaces is not None:
        # Per-interface MAC addresses are deliberately dropped.
        interfaces = [
            {
                "name": interface.name,
                "interface_type": interface.interface_type,
                "is_up": interface.is_up,
                "is_default_route": interface.is_default_route,
                "ipv4_addresses": list(interface.ipv4_addresses),
                "ipv6_addresses": list(interface.ipv6_addresses),
            }
            for interface in info.network_interfaces
        ]
    return {
        "identity": _section(
            info,
            [
                "manufacturer",
                "brand",
                "model",
                "device",
                "product",
                "board",
                "hardware",
                "soc",
            ],
        ),
        "software": _section(
            info,
            [
                "android_version",
                "api_level",
                "security_patch",
                "build_id",
                "build_number",
                "build_fingerprint",
                "build_tags",
                "build_type",
                "kernel",
                "kernel_version",
                "bootloader",
                "baseband",
                "uptime_seconds",
                "boot_time",
            ],
        ),
        "cpu_hardware": _section(
            info,
            [
                "processor",
                "architecture",
                "max_frequency_khz",
                "cpu_architecture",
                "cpu_abis",
                "cpu_core_count",
                "cpu_online_cores",
                "cpu_offline_cores",
                "cpu_governor",
                "cpu_features",
                "cpu_current_frequency_hz",
                "cpu_min_frequency_hz",
                "cpu_max_frequency_hz",
            ],
        ),
        "gpu": _section(info, ["gpu_vendor", "gpu_model"]),
        "display": _section(
            info,
            [
                "resolution",
                "density_dpi",
                "refresh_rate_hz",
                "orientation",
                "display_width_px",
                "display_height_px",
                "display_override_resolution",
                "display_override_density",
                "display_orientation_degrees",
                "supported_refresh_rates_hz",
            ],
        ),
        "storage": {
            "filesystem": info.storage_filesystem,
            "internal_volume": storage,
        },
        "network": {
            "interfaces": interfaces,
            "default_gateway": info.default_gateway,
            "default_interface": info.default_interface,
            "default_route_metric": info.default_route_metric,
            "dns_servers": _opt(info.dns_servers),
            "wifi_enabled": info.wifi_enabled,
            "wifi_connected": info.wifi_connected,
            "wifi_ssid": info.wifi_ssid,
            "wifi_frequency_mhz": info.wifi_frequency_mhz,
            "wifi_link_speed_mbps": info.wifi_link_speed_mbps,
            "wifi_rssi_dbm": info.wifi_rssi_dbm,
            "active_transport": info.active_transport,
            "vpn_active": info.vpn_active,
            "vpn_interface": info.vpn_interface,
        },
        "security": _section(
            info,
            [
                "selinux_status",
                "verified_boot_state",
                "bootloader_locked",
                "root_status",
                "debuggable",
                "secure_build",
                "encryption_state",
                "encryption_type",
                "verity_mode",
            ],
        ),
    }


def _battery_section(snapshot: BatterySnapshot | None) -> dict[str, Any] | None:
    """Live battery state, or ``None`` when no sample exists yet."""
    if snapshot is None:
        return None
    return {
        "timestamp": snapshot.timestamp,
        "level_percent": snapshot.level_percent,
        "scale": snapshot.scale,
        "voltage_mv": snapshot.voltage_mv,
        "temperature_c": snapshot.temperature_c,
        "status": snapshot.status.label,
        "status_raw": snapshot.status_raw,
        "health": snapshot.health.label,
        "health_raw": snapshot.health_raw,
        "present": snapshot.present,
        "ac_powered": snapshot.ac_powered,
        "usb_powered": snapshot.usb_powered,
        "wireless_powered": snapshot.wireless_powered,
        "technology": snapshot.technology,
        "charge_counter": snapshot.charge_counter,
    }


def _memory_section(snapshot: MemorySnapshot | None) -> dict[str, Any] | None:
    """Live memory state, or ``None`` when no sample exists yet."""
    if snapshot is None:
        return None
    return {
        "timestamp": snapshot.timestamp,
        "total_kb": snapshot.total_kb,
        "free_kb": snapshot.free_kb,
        "available_kb": snapshot.available_kb,
        "used_kb": snapshot.used_kb,
        "buffers_kb": snapshot.buffers_kb,
        "cached_kb": snapshot.cached_kb,
        "swap_cached_kb": snapshot.swap_cached_kb,
    }


def _cpu_section(snapshot: CPUSnapshot | None) -> dict[str, Any] | None:
    """Live CPU state, or ``None`` when no sample exists yet."""
    if snapshot is None:
        return None
    return {
        "timestamp": snapshot.timestamp,
        "aggregate_utilization_percent": snapshot.aggregate_utilization_percent,
        "cores": [
            {
                "core_id": core.core_id,
                "utilization_percent": core.utilization_percent,
                "frequency_khz": core.frequency_khz,
                "frequency_available": core.frequency_available,
            }
            for core in snapshot.cores
        ],
    }


def _diagnostics_section(report: DiagnosticReport | None) -> list[dict[str, Any]] | None:
    """The diagnostics findings, verbatim and in report order.

    ``None`` means "no evaluation exists yet"; an empty list means "the
    evaluation found no issues". Both states are preserved distinctly.
    """
    if report is None:
        return None
    return [
        {
            "severity": finding.severity.label,
            "category": finding.category.value,
            "title": finding.title,
            "what": finding.what,
            "why": finding.why,
            "evidence": finding.evidence,
            "recommended_action": finding.recommended_action,
        }
        for finding in report.findings
    ]


# ---------------------------------------------------------------------------
# Canonical payload + integrity
# ---------------------------------------------------------------------------


def payload_to_dict(payload: DeviceReportPayload) -> dict[str, Any]:
    """Serialize the payload to a JSON-ready dict (fixed key order).

    ``integrity`` is appended last so the digest can cover everything else.
    """
    body: dict[str, Any] = {
        "report_type": REPORT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "generated_at": payload.generated_at.isoformat(),
        "application_version": __version__,
        "device_serial": payload.device_serial,
        "device": _info_section(payload.info) if payload.info is not None else None,
        "battery": _battery_section(payload.battery),
        "memory": _memory_section(payload.memory),
        "cpu": _cpu_section(payload.cpu),
        "diagnostics": _diagnostics_section(payload.diagnostics),
    }
    body["integrity"] = {
        "algorithm": "sha256",
        "value": _integrity_digest(body),
    }
    return body


def _integrity_digest(body: dict[str, Any]) -> str:
    """SHA-256 over the canonical compact JSON of *body*."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def device_report_json(payload: DeviceReportPayload) -> str:
    """Render the report as deterministic, indented JSON."""
    return json.dumps(
        payload_to_dict(payload), indent=2, sort_keys=True, ensure_ascii=False
    )


def write_device_report(payload: DeviceReportPayload, path: str | Path) -> None:
    """Write the JSON rendering to *path* (no directory creation)."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(device_report_json(payload))


# ---------------------------------------------------------------------------
# Deterministic filenames
# ---------------------------------------------------------------------------


def _sanitize_serial(serial: str) -> str:
    """Filesystem-safe serial token: only ``[0-9A-Za-z._-]``, length-capped."""
    cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", serial).strip("_")
    if not cleaned:
        cleaned = "device"
    return cleaned[:_SERIAL_MAX_LEN]


def device_report_filename(device_serial: str | None, generated_at: datetime) -> str:
    """A deterministic, filesystem-safe export filename.

    Example: ``device-report-R58M29ABCDE-2026-08-16_101530.json``. The
    timestamp is local-time formatted and only ``[0-9A-Za-z._-]`` characters
    are produced, so the name is safe on every platform.
    """
    stamp = generated_at.astimezone().strftime(_FILENAME_STAMP)
    token = _sanitize_serial(device_serial) if device_serial else "device"
    return f"device-report-{token}-{stamp}.json"


__all__ = [
    "DeviceReportPayload",
    "SCHEMA_VERSION",
    "REPORT_TYPE",
    "device_report_filename",
    "device_report_json",
    "payload_to_dict",
    "write_device_report",
]