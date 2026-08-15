"""Automated incident reporting.

Turns the application's existing monitoring output (baseline snapshots,
drift events, heuristic signals, permission audits, socket and process
evidence) into one deterministic, exportable investigation artifact — the
:class:`IncidentReport`.

This package is a pure aggregation/presentation layer: it adds no ADB
calls, no network requests, no device modification, and no new collection.
It preserves the existing layers' own wording (diff explanations, signal
reasons, "worth reviewing" permission framing) and never produces verdicts
("malware", "compromised") — the report is an investigation artifact, not a
definitive threat determination.

Renderers (JSON + HTML, both consuming the same model) live in
``renderers.py``; PDF is rendered in the GUI layer (``gui/incident_pdf.py``)
where the existing PySide6 tooling can produce it.
"""

from .builder import build_incident_report
from .models import (
    ASSESSMENT_INFORMATIONAL,
    ASSESSMENT_NONE,
    ASSESSMENT_REVIEW_RECOMMENDED,
    ASSESSMENT_REVIEW_REQUIRED,
    EVENT_BASELINE_CREATED,
    EVENT_DRIFT_CHECKED,
    EVENT_DRIFT_EVENT,
    EVENT_HEURISTICS_EVALUATED,
    EVENT_PERMISSION_AUDITED,
    EVENT_SIGNAL_GENERATED,
    FINDING_DRIFT,
    FINDING_PERMISSION_COMBINATION,
    FINDING_SUSPICIOUS_SIGNAL,
    SCHEMA_VERSION,
    SOURCE_CLI,
    SOURCE_GUI,
    SOURCE_MANUAL,
    STATUS_BASELINE,
    DeviceInfo,
    ExecutiveSummary,
    Finding,
    IncidentReport,
    IntegrityMetadata,
    NetworkEvidence,
    PackageEvidence,
    PermissionEvidence,
    ProcessEvidence,
    Recommendation,
    ReportMetadata,
    SeveritySummary,
    TimelineEvent,
)
from .renderers import (
    html_report,
    json_report,
    report_filename,
    report_to_dict,
    write_html_report,
    write_json_report,
)

__all__ = [
    "ASSESSMENT_INFORMATIONAL",
    "ASSESSMENT_NONE",
    "ASSESSMENT_REVIEW_RECOMMENDED",
    "ASSESSMENT_REVIEW_REQUIRED",
    "EVENT_BASELINE_CREATED",
    "EVENT_DRIFT_CHECKED",
    "EVENT_DRIFT_EVENT",
    "EVENT_HEURISTICS_EVALUATED",
    "EVENT_PERMISSION_AUDITED",
    "EVENT_SIGNAL_GENERATED",
    "FINDING_DRIFT",
    "FINDING_PERMISSION_COMBINATION",
    "FINDING_SUSPICIOUS_SIGNAL",
    "SCHEMA_VERSION",
    "SOURCE_CLI",
    "SOURCE_GUI",
    "SOURCE_MANUAL",
    "STATUS_BASELINE",
    "DeviceInfo",
    "ExecutiveSummary",
    "Finding",
    "IncidentReport",
    "IntegrityMetadata",
    "NetworkEvidence",
    "PackageEvidence",
    "PermissionEvidence",
    "ProcessEvidence",
    "Recommendation",
    "ReportMetadata",
    "SeveritySummary",
    "TimelineEvent",
    "build_incident_report",
    "html_report",
    "json_report",
    "report_filename",
    "report_to_dict",
    "write_html_report",
    "write_json_report",
]