"""Incident report renderers — JSON and HTML, both consuming the same
:class:`IncidentReport` model.

Both renderers are pure and deterministic (same report → identical bytes),
require no network access, and never parse GUI strings. ``report_to_dict``
is the canonical serialization used by the JSON renderer *and* by the
builder's integrity digest, so the two always agree.

Unavailable values stay honest: ``None`` serializes as JSON ``null`` and
renders as "Unavailable" in HTML — never as zero, never as an omitted key.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    CombinationFlag,
    DeviceInfo,
    ExecutiveSummary,
    Finding,
    IncidentReport,
    IntegrityMetadata,
    InvestigationSection,
    NetworkEvidence,
    PackageEvidence,
    PermissionEntry,
    PermissionEvidence,
    ProcessEvidence,
    Recommendation,
    ReportMetadata,
    SeveritySummary,
    TimelineEvent,
)

#: Top-level JSON payload keys, in fixed order (stable schema).
_PAYLOAD_KEYS = (
    "schema_version",
    "metadata",
    "device",
    "summary",
    "severity_summary",
    "timeline",
    "findings",
    "process_evidence",
    "network_evidence",
    "package_evidence",
    "permission_evidence",
    "recommendations",
    "investigation",
    "integrity",
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Canonical serialization (shared by JSON renderer and integrity digest)
# ---------------------------------------------------------------------------


def _permission_entry_to_dict(entry: PermissionEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "granted": entry.granted,
        "permission_type": entry.permission_type,
    }


def _combination_flag_to_dict(flag: CombinationFlag) -> dict[str, Any]:
    return {
        "flag_id": flag.flag_id,
        "matched_permissions": list(flag.matched_permissions),
        "description": flag.description,
    }


def _metadata_to_dict(metadata: ReportMetadata) -> dict[str, Any]:
    return {
        "report_id": metadata.report_id,
        "schema_version": metadata.schema_version,
        "generated_at": _iso(metadata.generated_at),
        "application_version": metadata.application_version,
        "source": metadata.source,
        "session_id": metadata.session_id,
        "baseline_created_at": _iso(metadata.baseline_created_at),
    }


def _device_to_dict(device: DeviceInfo) -> dict[str, Any]:
    return {
        "serial": device.serial,
        "label": device.label,
        "android_version": device.android_version,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "sdk_level": device.sdk_level,
        "architecture": device.architecture,
        "collection_timestamp": _iso(device.collection_timestamp),
    }


def _summary_to_dict(summary: ExecutiveSummary) -> dict[str, Any]:
    return {
        "text": summary.text,
        "drift_change_count": summary.drift_change_count,
        "signal_count": summary.signal_count,
        "finding_count": summary.finding_count,
        "heuristics_evaluated": summary.heuristics_evaluated,
    }


def _severity_summary_to_dict(summary: SeveritySummary) -> dict[str, Any]:
    return {
        "high": summary.high,
        "medium": summary.medium,
        "low": summary.low,
        "info": summary.info,
        "total": summary.total,
        "assessment": summary.assessment,
    }


def _timeline_event_to_dict(event: TimelineEvent) -> dict[str, Any]:
    return {
        "timestamp": _iso(event.timestamp),
        "event_type": event.event_type,
        "description": event.description,
        "severity": event.severity,
        "entity": event.entity,
    }


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "type": finding.type,
        "severity": finding.severity,
        "title": finding.title,
        "description": finding.description,
        "entity": finding.entity,
        "timestamp": _iso(finding.timestamp),
        "category": finding.category,
        "change_type": finding.change_type,
        "reasons": list(finding.reasons),
        "evidence_refs": list(finding.evidence_refs),
        "related_processes": list(finding.related_processes),
        "related_packages": list(finding.related_packages),
        "related_sockets": list(finding.related_sockets),
    }


def _process_evidence_to_dict(row: ProcessEvidence) -> dict[str, Any]:
    return {
        "reference": row.reference,
        "process_name": row.process_name,
        "uid": row.uid,
        "classification": row.classification,
        "baseline_status": row.baseline_status,
        "pid": row.pid,
        "state": row.state,
        "cpu_percent": row.cpu_percent,
        "memory_percent": row.memory_percent,
    }


def _network_evidence_to_dict(row: NetworkEvidence) -> dict[str, Any]:
    return {
        "reference": row.reference,
        "protocol": row.protocol,
        "local_address": row.local_address,
        "local_port": row.local_port,
        "remote_address": row.remote_address,
        "remote_port": row.remote_port,
        "state": row.state,
        "uid": row.uid,
        "baseline_status": row.baseline_status,
        "package_refs": list(row.package_refs),
    }


def _package_evidence_to_dict(row: PackageEvidence) -> dict[str, Any]:
    return {
        "reference": row.reference,
        "package_name": row.package_name,
        "uid": row.uid,
        "baseline_status": row.baseline_status,
        "audit_refs": list(row.audit_refs),
    }


def _permission_evidence_to_dict(row: PermissionEvidence) -> dict[str, Any]:
    return {
        "reference": row.reference,
        "package_name": row.package_name,
        "read_at": _iso(row.read_at),
        "parse_complete": row.parse_complete,
        "permissions": [_permission_entry_to_dict(e) for e in row.permissions],
        "granted_permissions": list(row.granted_permissions),
        "runtime_granted_permissions": list(row.runtime_granted_permissions),
        "combination_flags": [_combination_flag_to_dict(f) for f in row.combination_flags],
        "reasons": list(row.reasons),
    }


def _recommendation_to_dict(item: Recommendation) -> dict[str, Any]:
    return {
        "finding_refs": list(item.finding_refs),
        "text": item.text,
    }


def _integrity_to_dict(item: IntegrityMetadata) -> dict[str, Any]:
    return {
        "generated_at": _iso(item.generated_at),
        "application_version": item.application_version,
        "schema_version": item.schema_version,
        "session_id": item.session_id,
        "evidence_sha256": item.evidence_sha256,
    }


def _investigation_to_dict(section: InvestigationSection) -> dict[str, Any]:
    return {
        "meaningful_drift_count": section.meaningful_drift_count,
        "transient_drift_count": section.transient_drift_count,
        "uncertain_drift_count": section.uncertain_drift_count,
        "stability_summary": section.stability_summary,
    }


def report_to_dict(report: IncidentReport) -> dict[str, Any]:
    """Serialize a report to a JSON-ready dict with a fixed key order."""
    return {
        "schema_version": report.schema_version,
        "metadata": _metadata_to_dict(report.metadata),
        "device": _device_to_dict(report.device),
        "summary": _summary_to_dict(report.summary),
        "severity_summary": _severity_summary_to_dict(report.severity_summary),
        "timeline": [_timeline_event_to_dict(e) for e in report.timeline],
        "findings": [_finding_to_dict(f) for f in report.findings],
        "process_evidence": [_process_evidence_to_dict(r) for r in report.process_evidence],
        "network_evidence": [_network_evidence_to_dict(r) for r in report.network_evidence],
        "package_evidence": [_package_evidence_to_dict(r) for r in report.package_evidence],
        "permission_evidence": [
            _permission_evidence_to_dict(r) for r in report.permission_evidence
        ],
        "recommendations": [_recommendation_to_dict(r) for r in report.recommendations],
        "investigation": (
            _investigation_to_dict(report.investigation)
            if report.investigation is not None
            else None
        ),
        "integrity": _integrity_to_dict(report.integrity) if report.integrity is not None else None,
    }


def json_report(report: IncidentReport) -> str:
    """Render the report as canonical, deterministic JSON."""
    return json.dumps(report_to_dict(report), indent=2, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# HTML rendering (self-contained: inline CSS only, no external resources)
# ---------------------------------------------------------------------------


def _disp(value: Any) -> str:
    """Render one value honestly: ``None`` means "Unavailable"."""
    return "Unavailable" if value is None else str(value)


def _sev_class(severity: str | None) -> str:
    return {
        "HIGH": "sev-high",
        "MEDIUM": "sev-medium",
        "INFO": "sev-info",
    }.get(severity or "", "sev-info")


_CSS = """
:root { color-scheme: dark; }
body {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px; color: #d8dee6; background: #14181d;
    margin: 0; padding: 24px;
}
h1 { font-size: 20px; letter-spacing: 1px; margin: 0 0 4px 0; }
h2 { font-size: 14px; letter-spacing: 1px; color: #7a8794;
     border-bottom: 1px solid #2a323c; padding-bottom: 6px; margin: 28px 0 12px 0; }
p { margin: 4px 0; }
.section { background: #1d232b; border: 1px solid #2a323c; border-radius: 8px;
           padding: 12px 16px; margin-bottom: 14px; }
.muted { color: #7a8794; }
.kv { display: grid; grid-template-columns: 220px 1fr; gap: 2px 12px; margin: 6px 0; }
.kv b { color: #aab4c0; font-weight: 600; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
th { text-align: left; color: #7a8794; font-size: 11px; letter-spacing: 0.5px;
     padding: 4px 8px; border-bottom: 1px solid #2a323c; }
td { padding: 4px 8px; border-bottom: 1px solid #232b35; vertical-align: top; }
.finding { border: 1px solid #2a323c; border-radius: 6px; padding: 10px 12px; margin: 8px 0; }
.finding-head { display: flex; gap: 10px; align-items: baseline; }
.sev-high { color: #ff5f56; font-weight: 600; }
.sev-medium { color: #f5a524; font-weight: 600; }
.sev-info { color: #aab4c0; font-weight: 600; }
.ref { color: #3d9be9; font-family: Consolas, monospace; font-size: 12px; }
.ul { margin: 4px 0 4px 18px; padding: 0; }
.li { margin: 2px 0; }
pre { white-space: pre-wrap; word-break: break-word; }
footer { margin-top: 28px; color: #7a8794; font-size: 12px; border-top: 1px solid #2a323c;
         padding-top: 10px; }
@media print {
    :root { color-scheme: light; }
    body { background: #ffffff; color: #111111; }
    .section { background: #ffffff; border-color: #cccccc; }
    th { color: #555555; border-bottom-color: #cccccc; }
    td { border-bottom-color: #eeeeee; }
    footer { color: #555555; border-top-color: #cccccc; }
}
"""


def _esc(value: Any) -> str:
    return html.escape(_disp(value))


def html_report(report: IncidentReport) -> str:
    """Render the report as a self-contained, print-friendly HTML document.

    Contains no external resources (no links, images or scripts), so it
    renders offline and is safe to open on any machine.
    """
    m = report.metadata
    d = report.device
    s = report.severity_summary
    integrity = report.integrity

    metadata_rows = [
        ("Report ID", _esc(m.report_id)),
        ("Application", _esc(f"Android Task Manager v{m.application_version}")),
        ("Schema version", _esc(m.schema_version)),
        ("Generated", _esc(m.generated_at)),
        ("Generation source", _esc(m.source)),
        ("Session ID", _esc(m.session_id)),
        ("Baseline created", _esc(m.baseline_created_at)),
    ]
    device_rows = [
        ("Device serial", _esc(d.serial)),
        ("Device label", _esc(d.label)),
        ("Android version", _esc(d.android_version)),
        ("Manufacturer", _esc(d.manufacturer)),
        ("Model", _esc(d.model)),
        ("SDK level", _esc(d.sdk_level)),
        ("Architecture", _esc(d.architecture)),
        ("Collection timestamp", _esc(d.collection_timestamp)),
    ]

    timeline_rows = "".join(
        "<tr>"
        f"<td class='muted'>{_esc(e.timestamp)}</td>"
        f"<td class='{_sev_class(e.severity)}'>{_esc(e.severity)}</td>"
        f"<td>{_esc(e.event_type)}</td>"
        f"<td>{_esc(e.description)}</td>"
        f"<td>{_esc(e.entity)}</td>"
        "</tr>"
        for e in report.timeline
    )

    findings_html = "".join(_finding_html(f) for f in report.findings)

    proc_rows = "".join(
        "<tr>"
        f"<td class='ref'>{_esc(r.reference)}</td>"
        f"<td>{_esc(r.process_name)}</td>"
        f"<td>{_esc(r.uid)}</td>"
        f"<td>{_esc(r.classification)}</td>"
        f"<td>{_esc(r.baseline_status)}</td>"
        f"<td>{_esc(r.pid)}</td>"
        f"<td>{_esc(r.cpu_percent)}</td>"
        f"<td>{_esc(r.memory_percent)}</td>"
        "</tr>"
        for r in report.process_evidence
    )
    net_rows = "".join(
        "<tr>"
        f"<td class='ref'>{_esc(r.reference)}</td>"
        f"<td>{_esc(r.protocol)}</td>"
        f"<td>{_esc(r.local_address)}</td>"
        f"<td>{_esc(r.local_port)}</td>"
        f"<td>{_esc(r.remote_address)}</td>"
        f"<td>{_esc(r.remote_port)}</td>"
        f"<td>{_esc(r.state)}</td>"
        f"<td>{_esc(r.uid)}</td>"
        f"<td>{_esc(r.baseline_status)}</td>"
        f"<td class='ref'>{_esc(', '.join(r.package_refs))}</td>"
        "</tr>"
        for r in report.network_evidence
    )
    pkg_rows = "".join(
        "<tr>"
        f"<td class='ref'>{_esc(r.reference)}</td>"
        f"<td>{_esc(r.package_name)}</td>"
        f"<td>{_esc(r.uid)}</td>"
        f"<td>{_esc(r.baseline_status)}</td>"
        f"<td class='ref'>{_esc(', '.join(r.audit_refs))}</td>"
        "</tr>"
        for r in report.package_evidence
    )
    perm_html = "".join(_permission_html(r) for r in report.permission_evidence)
    rec_html = "".join(
        f"<li class='li'><span class='ref'>{_esc(', '.join(r.finding_refs))}</span> "
        f"— {_esc(r.text)}</li>"
        for r in report.recommendations
    )

    if report.findings:
        findings_section = (
            "<h2>Findings</h2>"
            + findings_html
        )
    else:
        findings_section = (
            "<h2>Findings</h2><p class='muted'>No findings were recorded for this session.</p>"
        )
    if report.process_evidence:
        process_section = (
            "<h2>Process Evidence</h2>"
            "<table><tr><th>Ref</th><th>Process</th><th>UID</th><th>Classification</th>"
            "<th>Baseline</th><th>PID</th><th>CPU %</th><th>MEM %</th></tr>"
            + proc_rows
            + "</table>"
        )
    else:
        process_section = "<h2>Process Evidence</h2><p class='muted'>No related process evidence.</p>"
    if report.network_evidence:
        network_section = (
            "<h2>Network Evidence</h2>"
            "<table><tr><th>Ref</th><th>Proto</th><th>Local</th><th>Port</th>"
            "<th>Remote</th><th>RPort</th><th>State</th><th>UID</th><th>Baseline</th>"
            "<th>Packages</th></tr>"
            + net_rows
            + "</table>"
        )
    else:
        network_section = "<h2>Network Evidence</h2><p class='muted'>No related network evidence.</p>"
    if report.package_evidence:
        package_section = (
            "<h2>Package Evidence</h2>"
            "<table><tr><th>Ref</th><th>Package</th><th>UID</th><th>Baseline</th>"
            "<th>Audits</th></tr>"
            + pkg_rows
            + "</table>"
        )
    else:
        package_section = "<h2>Package Evidence</h2><p class='muted'>No related package evidence.</p>"
    if report.permission_evidence:
        permission_section = "<h2>Permission Evidence</h2>" + perm_html
    else:
        permission_section = (
            "<h2>Permission Evidence</h2>"
            "<p class='muted'>Permission audits are unavailable for this session.</p>"
        )
    if report.recommendations:
        recommendation_section = (
            "<h2>Recommended Investigation</h2><ul class='ul'>" + rec_html + "</ul>"
        )
    else:
        recommendation_section = (
            "<h2>Recommended Investigation</h2>"
            "<p class='muted'>No investigation steps are required for this session.</p>"
        )
    if report.investigation is not None:
        inv = report.investigation
        investigation_section = (
            "<div class='section'>\n"
            "<h2>Drift Stability</h2>"
            "<table><tr><th>Meaningful</th><th>Transient</th>"
            "<th>Unconfirmed</th></tr>"
            f"<tr><td>{inv.meaningful_drift_count}</td>"
            f"<td>{inv.transient_drift_count}</td>"
            f"<td>{inv.uncertain_drift_count}</td></tr></table>"
            f"<p>{_esc(inv.stability_summary)}</p>"
            "<p class='muted'>Transient and unconfirmed changes are listed in the "
            "timeline (TRANSIENT_CHANGE / NOT_OBSERVED) and were not promoted "
            "to findings.</p>"
            "</div>\n"
        )
    else:
        investigation_section = ""

    return (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "<meta charset='utf-8'>\n"
        f"<title>Incident Report {_esc(m.report_id)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>ANDROID SECURITY INVESTIGATION REPORT</h1>\n"
        f"<p class='muted'>{_esc(m.report_id)} &middot; "
        f"Android Task Manager v{_esc(m.application_version)}</p>\n"
        "<div class='section'>\n"
        "<h2>Report Metadata</h2>"
        + _kv_html(metadata_rows)
        + "</div>\n"
        "<div class='section'>\n"
        "<h2>Executive Summary</h2>"
        f"<p>{_esc(report.summary.text)}</p>"
        "</div>\n"
        "<div class='section'>\n"
        "<h2>Severity Summary</h2>"
        "<table><tr><th>Severity</th><th>Count</th></tr>"
        f"<tr><td class='sev-high'>HIGH</td><td>{s.high}</td></tr>"
        f"<tr><td class='sev-medium'>MEDIUM</td><td>{s.medium}</td></tr>"
        f"<tr><td class='sev-info'>LOW</td><td>{s.low}</td></tr>"
        f"<tr><td class='sev-info'>INFO</td><td>{s.info}</td></tr>"
        f"<tr><td>Total</td><td>{s.total}</td></tr></table>"
        f"<p><b>Assessment:</b> {_esc(s.assessment)}</p>"
        "</div>\n"
        "<div class='section'>\n"
        "<h2>Device Information</h2>"
        + _kv_html(device_rows)
        + "</div>\n"
        "<div class='section'>\n"
        "<h2>Investigation Timeline</h2>"
        "<table><tr><th>Timestamp</th><th>Severity</th><th>Type</th>"
        "<th>Description</th><th>Entity</th></tr>"
        + (timeline_rows if timeline_rows else "<tr><td colspan='5' class='muted'>"
          "No timed events were recorded.</td></tr>")
        + "</table>"
        "</div>\n"
        + findings_section
        + process_section
        + network_section
        + package_section
        + permission_section
        + recommendation_section
        + investigation_section
        + _integrity_html(integrity)
        + "<footer>"
        "This report is an investigation artifact generated from observed telemetry. "
        "It records what the monitoring session observed and preserves the existing "
        "analysis layers' own wording; it does not constitute a definitive malware "
        "verdict, and the integrity metadata detects accidental change rather than "
        "providing forensic immutability."
        "</footer>\n"
        "</body>\n"
        "</html>\n"
    )


def _kv_html(rows: list[tuple[str, str]]) -> str:
    return "<div class='kv'>" + "".join(
        f"<div><b>{key}</b></div><div>{value}</div>" for key, value in rows
    ) + "</div>"


def _finding_html(finding: Finding) -> str:
    refs = ", ".join(finding.evidence_refs) or "—"
    related = []
    if finding.related_processes:
        related.append("processes " + ", ".join(finding.related_processes))
    if finding.related_packages:
        related.append("packages " + ", ".join(finding.related_packages))
    if finding.related_sockets:
        related.append("sockets " + ", ".join(finding.related_sockets))
    related_text = "; ".join(related) if related else "—"
    reasons = "".join(f"<li class='li'>{_esc(r)}</li>" for r in finding.reasons)
    return (
        "<div class='finding'>"
        "<div class='finding-head'>"
        f"<span class='ref'>{_esc(finding.finding_id)}</span>"
        f"<span class='{_sev_class(finding.severity)}'>{_esc(finding.severity)}</span>"
        f"<span>{_esc(finding.type)}</span>"
        f"<span class='muted'>{_esc(finding.title)}</span>"
        "</div>"
        f"<p>{_esc(finding.description)}</p>"
        f"<p class='muted'>Entity: {_esc(finding.entity)} &middot; "
        f"Timestamp: {_esc(finding.timestamp)}</p>"
        f"<p class='muted'>Evidence: {_esc(refs)} &middot; "
        f"Related: {_esc(related_text)}</p>"
        + (f"<ul class='ul'>{reasons}</ul>" if reasons else "")
        + "</div>"
    )


def _permission_html(row: PermissionEvidence) -> str:
    flag_rows = "".join(
        "<tr>"
        f"<td class='ref'>{_esc(f.flag_id)}</td>"
        f"<td>{_esc(', '.join(f.matched_permissions))}</td>"
        f"<td>{_esc(f.description)}</td>"
        "</tr>"
        for f in row.combination_flags
    )
    perm_rows = "".join(
        "<tr>"
        f"<td>{_esc(p.name)}</td>"
        f"<td>{_esc(p.granted)}</td>"
        f"<td>{_esc(p.permission_type)}</td>"
        "</tr>"
        for p in row.permissions
    )
    return (
        "<div class='finding'>"
        f"<div class='finding-head'><span class='ref'>{_esc(row.reference)}</span>"
        f"<span>{_esc(row.package_name)}</span>"
        f"<span class='muted'>read {_esc(row.read_at)}</span></div>"
        f"<p class='muted'>Parse complete: {_esc(row.parse_complete)}</p>"
        + (
            "<table><tr><th>Flag</th><th>Matched permissions</th><th>Description</th></tr>"
            + flag_rows
            + "</table>"
            if flag_rows
            else "<p class='muted'>No combination flags.</p>"
        )
        + (
            "<table><tr><th>Permission</th><th>Granted</th><th>Type</th></tr>"
            + perm_rows
            + "</table>"
            if perm_rows
            else "<p class='muted'>No permissions were parsed.</p>"
        )
        + "</div>"
    )


def _integrity_html(integrity: IntegrityMetadata | None) -> str:
    if integrity is None:
        return "<h2>Evidence Integrity</h2><p class='muted'>Not available.</p>"
    return (
        "<h2>Evidence Integrity</h2>"
        "<div class='section'><div class='kv'>"
        f"<div><b>SHA-256 (report payload)</b></div><div><pre>{_esc(integrity.evidence_sha256)}</pre></div>"
        f"<div><b>Generated</b></div><div>{_esc(integrity.generated_at)}</div>"
        f"<div><b>Application</b></div><div>{_esc(integrity.application_version)}</div>"
        f"<div><b>Schema</b></div><div>{_esc(integrity.schema_version)}</div>"
        f"<div><b>Session</b></div><div>{_esc(integrity.session_id)}</div>"
        "</div>"
        "<p class='muted'>Integrity metadata detects accidental change; it does not "
        "provide forensic immutability.</p>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# File writing + deterministic filenames
# ---------------------------------------------------------------------------


def report_filename(generated_at: datetime, extension: str) -> str:
    """A deterministic, filesystem-safe report filename.

    Example: ``android_security_report_2026-08-15_224112.json``. The
    timestamp is local-time formatted; only ``[0-9A-Za-z._-]`` characters
    are produced, so the name is safe on every platform.
    """
    stamp = generated_at.astimezone().strftime("%Y-%m-%d_%H%M%S")
    extension = extension.lstrip(".")
    return f"android_security_report_{stamp}.{extension}"


def write_json_report(report: IncidentReport, path: str | Path) -> None:
    """Write the JSON rendering to *path* (no directory creation)."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json_report(report))


def write_html_report(report: IncidentReport, path: str | Path) -> None:
    """Write the HTML rendering to *path* (no directory creation)."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html_report(report))