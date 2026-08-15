"""Incident report — a structured, evidence-backed investigation artifact.

This layer converts the application's existing monitoring output (baseline
snapshots, drift events, heuristic signals, permission audits, socket and
process evidence) into one deterministic, exportable report. It is a pure
presentation/aggregation layer: it adds no ADB calls, no network requests,
no device modification, and no new collection — everything it consumes is
already produced by the existing trusted pipeline.

Facts vs. findings vs. interpretation (non-negotiable):

* **Facts** — the diff engine's ``DriftEvent`` objects and the raw socket /
  process / package / permission observations.
* **Findings** — the existing ``SuspiciousSignal`` objects (severity
  HIGH/MEDIUM) and permission combination flags (informational, INFO) the
  existing layers already produce, plus a structured view of every drift
  event (INFO).
* **Interpretation** — the deterministic executive summary and the
  investigation recommendations. Both are derived from counts and fixed
  per-type text; no LLM, no speculation, no verdicts.

The report is an *investigation artifact*, never a malware verdict: wording
is constrained ("warrants manual review", "was not present in baseline"),
and unverifiable values serialize honestly as ``None`` / "Unavailable" —
never zero, never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..baseline.models import SEVERITY_INFO, CHANGE_NEW, CHANGE_REMOVED
from ..heuristics.models import SEVERITY_HIGH, SEVERITY_MEDIUM
from ..network_investigation.models import SocketInfo
from ..permissions.models import CombinationFlag, PermissionEntry

#: Stable schema version of the report. Bump only on breaking changes to the
#: serialized structure (renderers must keep emitting it). v2 adds the
#: optional ``investigation`` stability section.
SCHEMA_VERSION = 2

#: Report generation sources (vocabulary; the GUI emits SOURCE_GUI).
SOURCE_GUI = "gui"
SOURCE_CLI = "cli"
SOURCE_MANUAL = "manual"

#: Timeline event types (stable schema keys).
EVENT_BASELINE_CREATED = "BASELINE_CREATED"
EVENT_DRIFT_EVENT = "DRIFT_EVENT"
EVENT_DRIFT_CHECKED = "DRIFT_CHECKED"
EVENT_HEURISTICS_EVALUATED = "HEURISTICS_EVALUATED"
EVENT_SIGNAL_GENERATED = "SIGNAL_GENERATED"
EVENT_PERMISSION_AUDITED = "PERMISSION_AUDITED"
#: Stability-annotated drift events (investigation core, v2).
EVENT_TRANSIENT_CHANGE = "TRANSIENT_CHANGE"
EVENT_NOT_OBSERVED = "NOT_OBSERVED"
EVENT_STABILITY_ANALYZED = "STABILITY_ANALYZED"

#: Finding types (stable schema keys).
FINDING_SUSPICIOUS_SIGNAL = "SUSPICIOUS_SIGNAL"
FINDING_DRIFT = "DRIFT"
FINDING_PERMISSION_COMBINATION = "PERMISSION_COMBINATION"

#: Evidence baseline status vocabulary. NEW/REMOVED reuse the diff engine's
#: change types; BASELINE means "present in both snapshots".
STATUS_BASELINE = "BASELINE"

#: Deterministic overall assessments, derived from severity counts only.
ASSESSMENT_NONE = "NO SIGNIFICANT FINDINGS"
ASSESSMENT_INFORMATIONAL = "INFORMATIONAL"
ASSESSMENT_REVIEW_RECOMMENDED = "REVIEW RECOMMENDED"
ASSESSMENT_REVIEW_REQUIRED = "REVIEW REQUIRED"


@dataclass(frozen=True)
class ReportMetadata:
    """Who produced this report, when, and for which session."""

    report_id: str
    generated_at: datetime
    application_version: str
    #: SOURCE_GUI | SOURCE_CLI | SOURCE_MANUAL.
    source: str = SOURCE_MANUAL
    schema_version: int = SCHEMA_VERSION
    #: ``None`` when the session carries no id (there is no session-id
    #: concept in the current project — represented honestly as unavailable).
    session_id: str | None = None
    #: The baseline this report compares against, when one exists.
    baseline_created_at: datetime | None = None


@dataclass(frozen=True)
class DeviceInfo:
    """Device metadata that was already available — nothing is collected
    for the report's sake, and nothing sensitive is ever included.

    Only ``serial`` (the ADB device serial from the baseline snapshot) and
    the optional display ``label`` / ``android_version`` are populated;
    every other field stays ``None`` ("unavailable") unless a future
    collector provides it. No secrets, no tokens, no fabricated ids.
    """

    serial: str | None
    label: str | None = None
    android_version: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    sdk_level: str | None = None
    architecture: str | None = None
    collection_timestamp: datetime | None = None


@dataclass(frozen=True)
class ExecutiveSummary:
    """A deterministic one-paragraph summary derived from actual counts.

    The sentence is assembled from the drift/signal/finding counts and the
    assessment; it never speculates ("hacked", "malware", "compromised"
    are never produced here).
    """

    text: str
    drift_change_count: int
    signal_count: int
    finding_count: int
    heuristics_evaluated: bool


@dataclass(frozen=True)
class SeveritySummary:
    """Finding counts per severity, using the project's existing severity
    vocabulary (HIGH/MEDIUM from heuristics, INFO from the diff engine).

    ``low`` is a reserved schema key: the project has no LOW severity in
    v1, so it is always zero — it exists for schema stability only.
    """

    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    @property
    def total(self) -> int:
        return self.high + self.medium + self.low + self.info

    @property
    def assessment(self) -> str:
        """The deterministic overall assessment derived from counts."""
        if self.high > 0:
            return ASSESSMENT_REVIEW_REQUIRED
        if self.medium > 0:
            return ASSESSMENT_REVIEW_RECOMMENDED
        if self.info > 0:
            return ASSESSMENT_INFORMATIONAL
        return ASSESSMENT_NONE


@dataclass(frozen=True)
class TimelineEvent:
    """One dated event on the investigation timeline.

    ``timestamp`` is ``None`` only when the source carried no time — the
    builder never fabricates one (every event the current pipeline emits
    does carry a real timestamp).
    """

    event_type: str
    description: str
    timestamp: datetime | None = None
    severity: str | None = None
    entity: str | None = None


@dataclass(frozen=True)
class Finding:
    """One structured finding: a signal, a drift fact, or a permission
    combination flag — always preserving the existing layer's own wording.

    * ``type`` — FINDING_SUSPICIOUS_SIGNAL | FINDING_DRIFT |
      FINDING_PERMISSION_COMBINATION.
    * ``category``/``change_type`` — set only for FINDING_DRIFT, so
      recommendations can be derived without re-parsing titles.
    * ``evidence_refs`` — references to the underlying drift events
      (``D-001``…).
    * ``related_processes/packages/sockets`` — references to the evidence
      rows (``P-001``, ``PKG-001``, ``S-001``) this finding points at.
    """

    finding_id: str
    type: str
    severity: str
    title: str
    description: str
    entity: str
    timestamp: datetime | None
    category: str | None = None
    change_type: str | None = None
    reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    related_processes: tuple[str, ...] = ()
    related_packages: tuple[str, ...] = ()
    related_sockets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessEvidence:
    """A process identity related to the findings, with optional dynamic
    metrics (pid/state/cpu/memory) when the latest process sample covered it.
    """

    reference: str  # "P-001"
    process_name: str
    uid: int | None
    classification: str  # ProcessCategory value ("kernel"|"system"|"user")
    #: STATUS_BASELINE | CHANGE_NEW | CHANGE_REMOVED.
    baseline_status: str
    pid: int | None = None
    state: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None


@dataclass(frozen=True)
class NetworkEvidence:
    """One socket related to the findings. Local identity comes from the
    baseline snapshot; connection detail (remote/state) is enriched from
    the most recent socket-table read when one was supplied.
    """

    reference: str  # "S-001"
    protocol: str
    local_address: str | None
    local_port: int | None
    remote_address: str | None
    remote_port: int | None
    state: str | None
    uid: int | None
    #: STATUS_BASELINE | CHANGE_NEW | CHANGE_REMOVED.
    baseline_status: str
    package_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageEvidence:
    """A package related to the findings, with its audit references."""

    reference: str  # "PKG-001"
    package_name: str
    uid: int | None
    #: STATUS_BASELINE | CHANGE_NEW | CHANGE_REMOVED.
    baseline_status: str
    audit_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionEvidence:
    """One existing ``PackagePermissionAudit``, unchanged — the report
    consumes the existing analyzer's output, never re-parses permissions.
    """

    reference: str  # "AUD-001"
    package_name: str
    read_at: datetime | None
    parse_complete: bool
    permissions: tuple[PermissionEntry, ...] = ()
    #: Names of entries the audit marked granted (``granted is True``).
    granted_permissions: tuple[str, ...] = ()
    #: Granted entries from the runtime section (dumpsys's "dangerous"
    #: tier) — the closest factual proxy for "sensitive" permissions.
    runtime_granted_permissions: tuple[str, ...] = ()
    combination_flags: tuple[CombinationFlag, ...] = ()
    #: The flags' own "worth reviewing" wording — preserved, never replaced.
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Recommendation:
    """One deterministic investigation step (never a remediation action).

    ``finding_refs`` lists the findings this step applies to; the text is
    investigation-focused — verifying, inspecting, comparing — and never
    recommends uninstalling, disabling, killing or deleting anything.
    """

    finding_refs: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class InvestigationSection:
    """Stability analysis of the session's drift (investigation core).

    Present only when the caller supplied the stability reports; the raw
    ``findings`` still contain every meaningful drift change, while
    transient and unconfirmed changes appear in the timeline with
    ``EVENT_TRANSIENT_CHANGE`` / ``EVENT_NOT_OBSERVED`` types instead of
    being promoted to findings.
    """

    meaningful_drift_count: int
    transient_drift_count: int
    uncertain_drift_count: int
    #: Deterministic, per-category summary sentence(s) joined by spaces.
    stability_summary: str


@dataclass(frozen=True)
class IntegrityMetadata:
    """Integrity metadata for the exported artifact.

    ``evidence_sha256`` is the SHA-256 (stdlib ``hashlib``) of the report's
    canonical JSON payload (every field except the integrity section
    itself). This is *integrity metadata* — it detects accidental change,
    not forensic immutability, and the wording stays honest about that.
    """

    generated_at: datetime
    application_version: str
    schema_version: int
    session_id: str | None
    evidence_sha256: str


@dataclass(frozen=True)
class IncidentReport:
    """The complete incident report: metadata, device, summary, severity
    summary, timeline, findings, evidence sections, recommendations and
    integrity metadata."""

    schema_version: int
    metadata: ReportMetadata
    device: DeviceInfo
    summary: ExecutiveSummary
    severity_summary: SeveritySummary
    timeline: tuple[TimelineEvent, ...] = ()
    findings: tuple[Finding, ...] = ()
    process_evidence: tuple[ProcessEvidence, ...] = ()
    network_evidence: tuple[NetworkEvidence, ...] = ()
    package_evidence: tuple[PackageEvidence, ...] = ()
    permission_evidence: tuple[PermissionEvidence, ...] = ()
    recommendations: tuple[Recommendation, ...] = ()
    investigation: InvestigationSection | None = None
    integrity: IntegrityMetadata | None = None


__all__ = [
    "ASSESSMENT_INFORMATIONAL",
    "ASSESSMENT_NONE",
    "ASSESSMENT_REVIEW_RECOMMENDED",
    "ASSESSMENT_REVIEW_REQUIRED",
    "CHANGE_NEW",
    "CHANGE_REMOVED",
    "EVENT_BASELINE_CREATED",
    "EVENT_DRIFT_CHECKED",
    "EVENT_DRIFT_EVENT",
    "EVENT_HEURISTICS_EVALUATED",
    "EVENT_NOT_OBSERVED",
    "EVENT_PERMISSION_AUDITED",
    "EVENT_SIGNAL_GENERATED",
    "EVENT_STABILITY_ANALYZED",
    "EVENT_TRANSIENT_CHANGE",
    "FINDING_DRIFT",
    "FINDING_PERMISSION_COMBINATION",
    "FINDING_SUSPICIOUS_SIGNAL",
    "SCHEMA_VERSION",
    "SEVERITY_HIGH",
    "SEVERITY_INFO",
    "SEVERITY_MEDIUM",
    "SOURCE_CLI",
    "SOURCE_GUI",
    "SOURCE_MANUAL",
    "STATUS_BASELINE",
    "CombinationFlag",
    "DeviceInfo",
    "ExecutiveSummary",
    "Finding",
    "IncidentReport",
    "IntegrityMetadata",
    "InvestigationSection",
    "NetworkEvidence",
    "PackageEvidence",
    "PermissionEvidence",
    "PermissionEntry",
    "ProcessEvidence",
    "Recommendation",
    "ReportMetadata",
    "SeveritySummary",
    "SocketInfo",
    "TimelineEvent",
]