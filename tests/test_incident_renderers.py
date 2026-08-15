"""Unit tests for the incident report renderers (JSON + HTML + filenames).

No device required. Verifies valid/deterministic JSON with a stable schema,
HTML that is self-contained (no external network dependency), honest
"Unavailable" rendering, escaping, integrity digest behavior, and the
deterministic filename helper.
"""

from __future__ import annotations

import json

from android_task_manager.incident.builder import build_incident_report
from android_task_manager.incident.renderers import (
    html_report,
    json_report,
    report_filename,
    report_to_dict,
    write_html_report,
    write_json_report,
)
from tests import incident_fixtures as fx

_TOP_LEVEL_KEYS = {
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
    "integrity",
}


def _report(scenario: str = "g"):
    return build_incident_report(**fx.ALL_SCENARIOS[scenario]())


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_is_valid_and_stable() -> None:
    for key in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j"):
        payload = json.loads(json_report(_report(key)))
        assert set(payload) == _TOP_LEVEL_KEYS, f"scenario {key}: schema drift"
        assert payload["schema_version"] == 1
        # No Python object repr leaks into the payload.
        assert " at 0x" not in json.dumps(payload)


def test_json_is_deterministic() -> None:
    first = json_report(_report())
    second = json_report(_report())
    assert first == second
    payload = json.loads(first)
    assert payload == json.loads(second)


def test_json_timestamps_are_iso_strings() -> None:
    payload = json.loads(json_report(_report("j")))
    generated = payload["metadata"]["generated_at"]
    assert generated == "2026-08-15T12:40:00+00:00"
    for event in payload["timeline"]:
        assert "T" in event["timestamp"]
        assert "+00:00" in event["timestamp"]


def test_json_unavailable_values_are_null_not_zero() -> None:
    payload = json.loads(json_report(_report("h")))
    process_row = payload["process_evidence"][0]
    assert process_row["uid"] is None
    assert process_row["cpu_percent"] == 0.0  # real zero stays zero
    assert payload["device"]["manufacturer"] is None
    assert payload["metadata"]["session_id"] is None


def test_json_contains_no_secret_like_keys() -> None:
    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in ("password", "token", "secret", "api_key", "auth"), key
                walk(value, path + (key,))
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(json.loads(json_report(_report("j"))), ())


def test_json_finding_fields_are_structured() -> None:
    payload = json.loads(json_report(_report("g")))
    finding = payload["findings"][0]
    assert finding["finding_id"].startswith("F-")
    assert finding["evidence_refs"]
    assert finding["related_processes"] or finding["related_sockets"]
    assert finding["severity"] in ("HIGH", "MEDIUM", "INFO")


def test_report_to_dict_matches_json_renderer() -> None:
    report = _report()
    assert report_to_dict(report) == json.loads(json_report(report))


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def test_html_contains_required_sections() -> None:
    document = html_report(_report("j"))
    for section in (
        "ANDROID SECURITY INVESTIGATION REPORT",
        "Report Metadata",
        "Executive Summary",
        "Severity Summary",
        "Device Information",
        "Investigation Timeline",
        "Findings",
        "Process Evidence",
        "Network Evidence",
        "Package Evidence",
        "Permission Evidence",
        "Recommended Investigation",
        "Evidence Integrity",
    ):
        assert section in document, section


def test_html_contains_findings_and_evidence() -> None:
    report = _report("g")
    document = html_report(report)
    assert "F-001" in document
    assert "MULTIPLE_NEW_LISTENING_SOCKETS_SAME_PROCESS" in document
    assert "com.example.newapp" in document
    assert "P-001" in document
    assert "S-001" in document
    assert "PKG-001" in document
    assert report.severity_summary.assessment in document


def test_html_has_no_external_network_dependency() -> None:
    document = html_report(_report())
    assert "http://" not in document
    assert "https://" not in document
    assert "<link" not in document
    assert "<img" not in document
    assert "<script" not in document
    assert "<iframe" not in document


def test_html_escapes_content() -> None:
    from android_task_manager.baseline.models import DriftEvent
    from android_task_manager.process.models import ProcessCategory

    baseline = fx.snapshot(
        processes=frozenset(
            {fx.proc("system_server", 1000, ProcessCategory.SYSTEM)}
        ),
        packages=frozenset({fx.pkg("com.example.app", 10200)}),
    )
    current = fx.snapshot(
        processes=frozenset(
            {
                fx.proc("system_server", 1000, ProcessCategory.SYSTEM),
                fx.proc('<script>alert("x")</script>', 1337, ProcessCategory.USER),
            }
        ),
        packages=frozenset({fx.pkg("com.example.app", 10200)}),
        created_at=fx.COMPARED_AT,
    )
    session = fx.session(
        baseline,
        current,
        events=(
            DriftEvent(
                category="process",
                change_type="new",
                entity='<script>alert("x")</script>',
                baseline_value=None,
                explanation="New process observed",
            ),
        ),
    )
    crafted = build_incident_report(
        session=session, heuristics=fx.heuristics(), generated_at=fx.GENERATED_AT
    )
    document = html_report(crafted)
    assert "<script>" not in document
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in document


def test_html_renders_unavailable_honestly() -> None:
    document = html_report(_report("h"))
    assert "Unavailable" in document


def test_html_is_deterministic() -> None:
    assert html_report(_report()) == html_report(_report())


def test_html_empty_report_has_honest_messages() -> None:
    document = html_report(_report("i"))
    assert "No findings were recorded for this session." in document
    assert "No related process evidence." in document
    assert "No related network evidence." in document
    assert "No related package evidence." in document


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_integrity_digest_matches_canonical_payload() -> None:
    import hashlib

    from android_task_manager.incident.renderers import report_to_dict

    report = _report()
    payload = report_to_dict(report)
    payload.pop("integrity", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert report.integrity is not None
    assert report.integrity.evidence_sha256 == expected


def test_integrity_changes_when_evidence_changes() -> None:
    first = _report("d")
    inputs = fx.scenario_d_new_socket()
    session = inputs["session"]
    from dataclasses import replace

    current = replace(
        session.current,
        sockets=frozenset(
            list(session.current.sockets)
            + [fx.sock("tcp", "0.0.0.0", 9999, 10210)]
        ),
    )
    inputs["session"] = replace(
        session,
        current=current,
        drift_report=replace(
            session.drift_report,
            events=session.drift_report.events
            + (fx.new_event("socket", "tcp:0.0.0.0:9999"),),
        ),
    )
    changed = build_incident_report(**inputs)
    assert changed.integrity.evidence_sha256 != first.integrity.evidence_sha256


# ---------------------------------------------------------------------------
# Filenames + writers
# ---------------------------------------------------------------------------


def test_report_filename_is_safe_and_deterministic() -> None:
    name = report_filename(fx.GENERATED_AT, "json")
    stamp = fx.GENERATED_AT.astimezone().strftime("%Y-%m-%d_%H%M%S")
    assert name == f"android_security_report_{stamp}.json"
    assert report_filename(fx.GENERATED_AT, ".json") == name
    assert report_filename(fx.GENERATED_AT, "html").endswith(".html")
    assert report_filename(fx.GENERATED_AT, "pdf").endswith(".pdf")
    import string

    allowed = set(string.ascii_letters + string.digits + "._-")
    assert set(name) <= allowed


def test_write_json_and_html_helpers(tmp_path) -> None:
    report = _report("g")
    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"
    write_json_report(report, json_path)
    write_html_report(report, html_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["metadata"]["report_id"] == (
        report.metadata.report_id
    )
    assert "ANDROID SECURITY INVESTIGATION REPORT" in html_path.read_text(encoding="utf-8")