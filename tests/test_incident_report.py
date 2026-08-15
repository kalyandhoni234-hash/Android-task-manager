"""Unit tests for the incident report builder.

No device required — all scenarios are synthetic and in-memory. Covers
report building across the fixture scenarios, severity counting, the
deterministic timeline, evidence honesty (None stays None, zero stays
zero), reference traceability, determinism, recommendations, integrity,
and the read-only safety guarantees.
"""

from __future__ import annotations

import inspect
import re

import pytest

from android_task_manager.baseline.export import Session
from android_task_manager.baseline.models import (
    CATEGORY_PACKAGE,
    CATEGORY_PROCESS,
    CATEGORY_SOCKET,
    CHANGE_NEW,
)
from android_task_manager.heuristics.models import SEVERITY_HIGH, SEVERITY_MEDIUM
from android_task_manager.incident.builder import build_incident_report
from android_task_manager.incident.models import (
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
    STATUS_BASELINE,
    IncidentReport,
)
from tests import incident_fixtures as fx


def _report(scenario: str) -> IncidentReport:
    return fx.build_for(scenario)


# ---------------------------------------------------------------------------
# Report building — scenarios A–J
# ---------------------------------------------------------------------------


def test_empty_session_produces_empty_report() -> None:
    report = _report("i")
    assert isinstance(report, IncidentReport)
    assert report.schema_version == SCHEMA_VERSION
    assert report.findings == ()
    assert report.severity_summary.total == 0
    assert report.severity_summary.assessment == ASSESSMENT_NONE
    assert report.process_evidence == ()
    assert report.network_evidence == ()
    assert report.package_evidence == ()
    assert report.permission_evidence == ()
    assert report.recommendations == ()
    assert report.metadata.report_id == "ATM-20260815-001"


def test_normal_session_has_no_findings_and_informational_assessment() -> None:
    report = _report("a")
    assert report.findings == ()
    assert report.severity_summary.assessment == ASSESSMENT_NONE
    assert report.summary.heuristics_evaluated is True
    assert report.summary.drift_change_count == 0
    assert report.summary.signal_count == 0


def test_new_process_scenario_reports_drift_finding_and_evidence() -> None:
    report = _report("b")
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.type == FINDING_DRIFT
    assert finding.category == CATEGORY_PROCESS
    assert finding.change_type == CHANGE_NEW
    assert finding.entity == "com.example.daemon"
    assert finding.severity == "INFO"
    assert finding.evidence_refs == ("D-001",)
    assert finding.related_processes == ("P-001",)
    assert [r.process_name for r in report.process_evidence] == ["com.example.daemon"]
    assert report.process_evidence[0].baseline_status == CHANGE_NEW


def test_new_package_scenario_reports_drift_finding_and_evidence() -> None:
    report = _report("c")
    finding = report.findings[0]
    assert finding.category == CATEGORY_PACKAGE
    assert finding.entity == "com.example.installed"
    assert finding.related_packages == ("PKG-001",)
    assert report.package_evidence[0].package_name == "com.example.installed"
    assert report.package_evidence[0].baseline_status == CHANGE_NEW


def test_new_socket_scenario_reports_drift_finding_and_network_evidence() -> None:
    report = _report("d")
    finding = report.findings[0]
    assert finding.category == CATEGORY_SOCKET
    assert finding.entity == "tcp:0.0.0.0:4444"
    assert finding.related_sockets == ("S-001",)
    row = report.network_evidence[0]
    assert row.reference == "S-001"
    assert row.protocol == "tcp"
    assert row.local_address == "0.0.0.0"
    assert row.local_port == 4444
    assert row.baseline_status == CHANGE_NEW
    # Enriched detail from the socket-table read (when supplied).
    assert row.state == "LISTEN"
    # The owning package (from the network snapshot's uid→package map).
    assert row.package_refs == ("PKG-001",)
    assert [p.package_name for p in report.package_evidence] == ["com.example.other"]


def test_high_signal_scenario_creates_high_finding() -> None:
    report = _report("e")
    assert report.severity_summary.high == 1
    assert report.severity_summary.medium == 0
    assert report.severity_summary.assessment == ASSESSMENT_REVIEW_REQUIRED
    signal_findings = [f for f in report.findings if f.type == FINDING_SUSPICIOUS_SIGNAL]
    assert len(signal_findings) == 1
    finding = signal_findings[0]
    assert finding.severity == SEVERITY_HIGH
    assert finding.entity == "uid=10200"
    # The signal's contributing drift events became D-references.
    assert finding.evidence_refs == ("D-001", "D-002")
    # uid=10200 resolves to both new sockets.
    assert finding.related_sockets == ("S-001", "S-002")
    assert report.severity_summary.total == 3  # 1 signal + 2 drift INFO


def test_permission_finding_scenario_creates_info_finding() -> None:
    report = _report("f")
    perm_findings = [
        f for f in report.findings if f.type == FINDING_PERMISSION_COMBINATION
    ]
    assert len(perm_findings) == 1
    finding = perm_findings[0]
    assert finding.severity == "INFO"
    assert finding.entity == "com.example.smsapp"
    assert "worth reviewing" in finding.description
    assert finding.related_packages == ("PKG-001",)
    assert len(report.permission_evidence) == 1
    row = report.permission_evidence[0]
    assert row.reference == "AUD-001"
    assert row.granted_permissions == (
        "android.permission.INTERNET",
        "android.permission.READ_SMS",
        "android.permission.VIBRATE",
    )
    # Only runtime-granted permissions are broken out separately.
    assert row.runtime_granted_permissions == (
        "android.permission.INTERNET",
        "android.permission.READ_SMS",
    )
    assert row.reasons == (finding.description,)
    assert row.parse_complete is True


def test_correlated_scenario_generates_all_rule_signals() -> None:
    report = _report("g")
    assert report.severity_summary.high == 1
    assert report.severity_summary.medium == 2
    assert report.summary.signal_count == 3
    types = {f.type for f in report.findings}
    assert types == {FINDING_SUSPICIOUS_SIGNAL, FINDING_DRIFT}
    # Findings sorted HIGH first, then MEDIUM, then INFO.
    severities = [f.severity for f in report.findings]
    assert severities == sorted(severities, key=lambda s: {"HIGH": 0, "MEDIUM": 1, "INFO": 2}[s])
    # Process evidence enriched from the process sample.
    row = next(r for r in report.process_evidence if r.process_name == "com.example.newapp")
    assert row.pid == 18472
    assert row.cpu_percent == 12.5
    assert row.memory_percent == 3.0
    assert row.baseline_status == CHANGE_NEW
    # Socket evidence links to the owning package.
    net_row = next(r for r in report.network_evidence if r.local_port == 4444)
    assert net_row.package_refs == ("PKG-001",)
    assert [p.package_name for p in report.package_evidence] == ["com.example.newapp"]


def test_unavailable_data_stays_unavailable() -> None:
    report = _report("h")
    proc_row = report.process_evidence[0]
    assert proc_row.uid is None
    # 0.0 is a real value, not "unavailable".
    assert proc_row.cpu_percent == 0.0
    assert proc_row.memory_percent == 0.0
    # No package changes in this scenario → no package evidence.
    assert report.package_evidence == ()
    # The unverified socket category produced no socket events or rows.
    assert report.network_evidence == ()


def test_mixed_scenario_j_counts_are_correct() -> None:
    report = _report("j")
    assert report.severity_summary.high == 1
    assert report.severity_summary.medium == 1
    assert report.severity_summary.info == 5  # 4 drift + 1 permission flag
    assert report.severity_summary.assessment == ASSESSMENT_REVIEW_REQUIRED
    assert len(report.permission_evidence) == 1


def test_report_without_heuristics_degrades_honestly() -> None:
    inputs = fx.scenario_b_new_process()
    inputs.pop("heuristics")
    report = build_incident_report(**inputs)
    assert report.summary.heuristics_evaluated is False
    assert "Heuristics were not evaluated for this session." in report.summary.text
    assert report.summary.signal_count == 0
    assert report.severity_summary.assessment == ASSESSMENT_INFORMATIONAL
    timeline_types = {e.event_type for e in report.timeline}
    assert EVENT_HEURISTICS_EVALUATED not in timeline_types
    assert EVENT_SIGNAL_GENERATED not in timeline_types


def test_heuristics_without_drift_still_reported() -> None:
    report = _report("a")
    assert EVENT_HEURISTICS_EVALUATED in {e.event_type for e in report.timeline}


# ---------------------------------------------------------------------------
# Severity summary
# ---------------------------------------------------------------------------


def test_severity_assessment_is_deterministic_and_honest() -> None:
    assert ASSESSMENT_NONE == "NO SIGNIFICANT FINDINGS"
    assert ASSESSMENT_INFORMATIONAL == "INFORMATIONAL"
    assert ASSESSMENT_REVIEW_RECOMMENDED == "REVIEW RECOMMENDED"
    assert ASSESSMENT_REVIEW_REQUIRED == "REVIEW REQUIRED"


def test_medium_only_assessment_is_review_recommended() -> None:
    inputs = fx.scenario_g_correlated()
    # Keep only the MEDIUM signals.
    inputs["heuristics"] = fx.heuristics(inputs["heuristics"].signals[1], inputs["heuristics"].signals[2])
    report = build_incident_report(**inputs)
    assert report.severity_summary.medium == 2
    assert report.severity_summary.assessment == ASSESSMENT_REVIEW_RECOMMENDED


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_builder_is_deterministic() -> None:
    for key in ("a", "b", "d", "e", "f", "g", "h", "i", "j"):
        first = _report(key)
        second = fx.build_for(key)
        assert first == second, f"scenario {key} is not deterministic"
        assert first.metadata.report_id == second.metadata.report_id


def test_summary_text_is_deterministic_and_contains_only_facts() -> None:
    report = _report("g")
    text = report.summary.text
    assert "4 change(s)" in text
    assert "3 suspicious signal(s)" in text
    assert "1 HIGH, 2 MEDIUM" in text
    # No speculative verdicts are ever produced.
    for banned in ("hacked", "malware", "compromised", "should be removed"):
        assert banned not in text


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_orders_events_chronologically() -> None:
    report = _report("g")
    timestamps = [e.timestamp for e in report.timeline]
    assert timestamps == sorted(timestamps)
    # Baseline creation precedes the drift check.
    types = [e.event_type for e in report.timeline]
    assert types.index(EVENT_BASELINE_CREATED) < types.index(EVENT_DRIFT_CHECKED)


def test_timeline_equal_timestamps_use_type_rank() -> None:
    report = _report("g")
    compared = [e for e in report.timeline if e.timestamp == fx.COMPARED_AT]
    assert len(compared) >= 5  # 4 drift events + drift check
    # DRIFT_EVENT events come before DRIFT_CHECKED at the same timestamp.
    types = [e.event_type for e in compared]
    assert types[-1] == EVENT_DRIFT_CHECKED
    for event_type in types[:-1]:
        assert event_type == EVENT_DRIFT_EVENT


def test_timeline_never_fabricates_timestamps() -> None:
    """Every timeline timestamp must come from a real input timestamp."""
    allowed = {
        fx.BASELINE_AT.isoformat(),
        fx.COMPARED_AT.isoformat(),
        fx.EVALUATED_AT.isoformat(),
        fx.AUDIT_AT.isoformat(),
    }
    for key in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j"):
        report = _report(key)
        for event in report.timeline:
            assert event.timestamp is not None
            assert event.timestamp.isoformat() in allowed, (
                f"scenario {key}: fabricated timestamp {event.timestamp}"
            )


def test_timeline_contains_signal_and_audit_events() -> None:
    report = _report("j")
    types = {e.event_type for e in report.timeline}
    assert EVENT_SIGNAL_GENERATED in types
    assert EVENT_PERMISSION_AUDITED in types
    audit_events = [e for e in report.timeline if e.event_type == EVENT_PERMISSION_AUDITED]
    assert audit_events[0].entity == "com.example.flagpkg"


# ---------------------------------------------------------------------------
# Evidence / traceability
# ---------------------------------------------------------------------------


def test_all_finding_references_resolve() -> None:
    for key in ("b", "c", "d", "e", "f", "g", "h", "j"):
        report = _report(key)
        proc_refs = {r.reference for r in report.process_evidence}
        pkg_refs = {r.reference for r in report.package_evidence}
        sock_refs = {r.reference for r in report.network_evidence}
        audit_refs = {r.reference for r in report.permission_evidence}
        drift_refs = {f"D-{i:03d}" for i in range(1, report.summary.drift_change_count + 1)}
        for finding in report.findings:
            for ref in finding.evidence_refs:
                assert ref in drift_refs, f"{ref} is not a drift ref"
            for ref in finding.related_processes:
                assert ref in proc_refs, f"{ref} is not a process ref"
            for ref in finding.related_packages:
                assert ref in pkg_refs, f"{ref} is not a package ref"
            for ref in finding.related_sockets:
                assert ref in sock_refs, f"{ref} is not a socket ref"
        for row in report.package_evidence:
            for ref in row.audit_refs:
                assert ref in audit_refs, f"{ref} is not an audit ref"
        # Network rows point at real packages.
        for row in report.network_evidence:
            for ref in row.package_refs:
                assert ref in pkg_refs, f"{ref} is not a package ref"


def test_socket_evidence_without_network_snapshot_is_honest() -> None:
    inputs = fx.scenario_d_new_socket()
    inputs.pop("network_investigation")
    report = build_incident_report(**inputs)
    row = report.network_evidence[0]
    assert row.state is None
    assert row.remote_address is None
    assert row.package_refs == ()


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def test_recommendations_are_investigation_only() -> None:
    report = _report("j")
    assert report.recommendations
    for recommendation in report.recommendations:
        assert recommendation.finding_refs
        lower = recommendation.text.lower()
        for banned in ("uninstall", "disable", "force-stop", "force stop", "kill", "delete", "remove"):
            assert banned not in lower, recommendation.text


def test_recommendations_are_deterministic_and_grouped_by_text() -> None:
    first = _report("g")
    second = fx.build_for("g")
    assert first.recommendations == second.recommendations
    texts = [r.text for r in first.recommendations]
    assert texts == sorted(texts)
    refs = [r.finding_refs for r in first.recommendations]
    assert all(tuple(sorted(r)) == r for r in refs)


def test_recommendation_texts_match_finding_types() -> None:
    report = _report("j")
    for recommendation in report.recommendations:
        assert recommendation.text.startswith(
            ("Review", "Verify", "Inspect", "Compare", "Confirm", "Cross-check")
        )


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_integrity_digest_is_deterministic() -> None:
    first = _report("g")
    second = fx.build_for("g")
    assert first.integrity is not None
    assert first.integrity.evidence_sha256 == second.integrity.evidence_sha256
    assert len(first.integrity.evidence_sha256) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", first.integrity.evidence_sha256)


def test_integrity_digest_changes_with_evidence() -> None:
    first = _report("d")
    inputs = fx.scenario_d_new_socket()
    current = fx.snapshot(
        processes=frozenset(),
        packages=frozenset(
            {fx.pkg("com.example.app", 10200), fx.pkg("com.example.other", 10210)}
        ),
        sockets=frozenset(
            {fx.sock("tcp", "0.0.0.0", 8080, 10200), fx.sock("tcp", "0.0.0.0", 9999, 10210)}
        ),
        created_at=fx.COMPARED_AT,
    )
    inputs["session"] = fx.session(
        inputs["session"].baseline,
        current,
        events=(fx.new_event(CATEGORY_SOCKET, "tcp:0.0.0.0:9999"),),
    )
    changed = build_incident_report(**inputs)
    assert changed.integrity is not None
    assert changed.integrity.evidence_sha256 != first.integrity.evidence_sha256


def test_integrity_uses_stdlib_sha256() -> None:
    import importlib

    module = importlib.import_module("android_task_manager.incident.builder")
    source = inspect.getsource(module)
    assert "hashlib" in source


# ---------------------------------------------------------------------------
# Safety (read-only guarantees)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    ["android_task_manager.incident.builder", "android_task_manager.incident.renderers"],
)
def test_report_modules_make_no_network_or_shell_calls(module_name: str) -> None:
    """The report layer performs no device modification, no package actions,
    no network requests and no shell commands: it must not even import the
    machinery for them."""
    import importlib

    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    for banned in (
        "import subprocess",
        "import urllib",
        "import socket",
        "import http",
        "import requests",
        "from urllib",
        "import adb",
    ):
        assert banned not in source, f"{module_name} imports {banned!r}"


def test_builder_accepts_a_session_without_any_runner() -> None:
    """Building needs no ADB/device object at all — it is a pure function
    of already-collected data."""
    report = _report("g")
    assert report.findings
    assert report.device.serial == fx.SERIAL


# ---------------------------------------------------------------------------
# Metadata / report id
# ---------------------------------------------------------------------------


def test_report_id_format_and_sequence() -> None:
    first = _report("i")
    assert first.metadata.report_id == "ATM-20260815-001"
    inputs = fx.scenario_i_empty()
    inputs["sequence"] = 42
    inputs["source"] = "cli"
    report = build_incident_report(**inputs)
    assert report.metadata.report_id == "ATM-20260815-042"
    assert report.metadata.source == "cli"
    assert report.metadata.generated_at == fx.GENERATED_AT
    assert report.metadata.baseline_created_at == fx.BASELINE_AT
    assert report.metadata.session_id is None  # honest: no session id concept


def test_device_info_is_honest_when_unavailable() -> None:
    report = _report("i")
    assert report.device.serial == fx.SERIAL
    assert report.device.manufacturer is None
    assert report.device.model is None
    assert report.device.collection_timestamp == fx.BASELINE_AT
    inputs = fx.scenario_i_empty()
    inputs["device_label"] = "Vivo V2026"
    inputs["android_version"] = "11"
    report = build_incident_report(**inputs)
    assert report.device.label == "Vivo V2026"
    assert report.device.android_version == "11"


def test_serial_never_fabricated() -> None:
    inputs = fx.scenario_i_empty()
    empty_snapshot = fx.snapshot()
    from dataclasses import replace

    inputs["session"] = Session(
        baseline=replace(empty_snapshot, device_serial=""),
        current=replace(empty_snapshot, device_serial=""),
        drift_report=inputs["session"].drift_report,
    )
    report = build_incident_report(**inputs)
    assert report.device.serial is None


def test_summary_never_claims_certainty() -> None:
    for key in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j"):
        report = _report(key)
        for banned in ("is malware", "is malicious", "is compromised", "has been hacked"):
            assert banned not in report.summary.text


# ---------------------------------------------------------------------------
# Mixed/edge behavior
# ---------------------------------------------------------------------------


def test_removed_process_evidence_comes_from_baseline() -> None:
    from android_task_manager.baseline.models import CHANGE_REMOVED, DriftEvent
    from android_task_manager.process.models import ProcessCategory

    baseline = fx.snapshot(
        processes=frozenset(
            {
                fx.proc("system_server", 1000, ProcessCategory.SYSTEM),
                fx.proc("com.example.old", 10200, ProcessCategory.USER),
            }
        ),
        packages=frozenset({fx.pkg("com.example.app", 10200)}),
    )
    current = fx.snapshot(
        processes=frozenset({fx.proc("system_server", 1000, ProcessCategory.SYSTEM)}),
        packages=frozenset({fx.pkg("com.example.app", 10200)}),
        created_at=fx.COMPARED_AT,
    )
    drift = fx.session(
        baseline,
        current,
        events=(
            DriftEvent(
                category=CATEGORY_PROCESS,
                change_type=CHANGE_REMOVED,
                entity="com.example.old",
                baseline_value="com.example.old (uid 10200, user)",
                explanation="Process no longer observed",
            ),
        ),
    )
    report = build_incident_report(
        session=drift, heuristics=fx.heuristics(), generated_at=fx.GENERATED_AT
    )
    finding = report.findings[0]
    assert finding.change_type == CHANGE_REMOVED
    assert finding.entity == "com.example.old"
    assert "Process no longer observed" in finding.description
    row = report.process_evidence[0]
    assert row.process_name == "com.example.old"
    assert row.baseline_status == CHANGE_REMOVED
    assert row.uid == 10200


def test_empty_session_does_not_crash_any_scenario() -> None:
    for key in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j"):
        report = _report(key)
        assert report.metadata.report_id.startswith("ATM-")