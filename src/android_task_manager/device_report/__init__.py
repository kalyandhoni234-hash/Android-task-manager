"""Device report export: a deterministic, evidence-backed local JSON artifact.

A pure serialization layer on top of the already-collected models — it adds
no ADB traffic, never touches the Android device, and only writes a local
file when explicitly asked to. See ``render.py`` for the full design rules
(determinism, SHA-256 integrity, privacy exclusions).
"""

from .render import (
    REPORT_TYPE,
    SCHEMA_VERSION,
    DeviceReportPayload,
    device_report_filename,
    device_report_json,
    payload_to_dict,
    write_device_report,
)

__all__ = [
    "REPORT_TYPE",
    "SCHEMA_VERSION",
    "DeviceReportPayload",
    "device_report_filename",
    "device_report_json",
    "payload_to_dict",
    "write_device_report",
]