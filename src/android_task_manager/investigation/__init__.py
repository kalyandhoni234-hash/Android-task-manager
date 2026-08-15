"""Investigation core — stable drift, timeline, correlation, attribution,
evidence explanations and the process tree.

This package consumes the existing pipeline's output (baseline snapshots,
raw drift facts, heuristic signals, socket tables, permission audits) and
adds the evidence-first investigation layer:

* ``stability`` — snapshot completeness (COMPLETE/PARTIAL/FAILED) and
  observation stability (STABLE/TRANSIENT/PERSISTENT/UNCERTAIN/REMOVED)
  so raw drift is promoted to *meaningful drift* only on stable evidence.
* ``timeline`` — the unified, deterministic investigation timeline and
  non-causal entity correlation.
* ``attribution`` — socket → PID → process → UID → package, honestly
  labeled FULL / PARTIAL / UNAVAILABLE.
* ``explain`` — the "why was this flagged?" evidence panel: facts only,
  derived from collected data, never verdicts.
* ``tree`` — a read-only parent/child view of one process snapshot.

Everything is pure and read-only, mirroring the rest of the application.
"""

from .attribution import attribute_socket, attribute_sockets
from .completeness import (
    baseline_category_completeness,
    snapshot_completeness,
    socket_table_completeness,
)
from .explain import entity_stability_for, explain_signal
from .models import (
    ATTRIBUTION_STATES,
    EVENT_BASELINE_CREATED,
    EVENT_DRIFT_CHECKED,
    EVENT_DRIFT_EVENT,
    EVENT_HEURISTICS_EVALUATED,
    EVENT_NOT_OBSERVED,
    EVENT_PERMISSION_AUDITED,
    EVENT_SIGNAL_GENERATED,
    EVENT_STABILITY_ANALYZED,
    EVENT_TRANSIENT_CHANGE,
    FACT_BASELINE,
    FACT_NETWORK,
    FACT_PACKAGE,
    FACT_PERMISSION,
    FACT_PROCESS,
    FACT_SIGNAL,
    RELATION_ASSOCIATED_WITH,
    RELATION_OBSERVED_ON,
    RELATION_OWNED_BY,
    RELATION_RELATED_TO,
    STABILITY_MEANINGFUL,
    STABILITY_TRANSIENT,
    STABILITY_UNCERTAIN,
    AttributionState,
    EntityStability,
    EvidenceExplanation,
    EvidenceFact,
    InvestigationEvent,
    Observation,
    ObservationState,
    ProcessNode,
    ProcessTree,
    RelatedEntities,
    SnapshotCompleteness,
    SocketAttribution,
    StabilityReport,
)
from .stability import (
    MIN_PERSISTENT_OBSERVATIONS,
    STABILITY_CATEGORIES,
    TRACKER_WINDOW,
    ObservationTracker,
    classify_entity_state,
    first_observed_by_key,
    stabilize_drift,
)
from .timeline import build_investigation_timeline, correlate_entity
from .tree import build_process_tree, format_tree

__all__ = [
    "ATTRIBUTION_STATES",
    "EVENT_BASELINE_CREATED",
    "EVENT_DRIFT_CHECKED",
    "EVENT_DRIFT_EVENT",
    "EVENT_HEURISTICS_EVALUATED",
    "EVENT_NOT_OBSERVED",
    "EVENT_PERMISSION_AUDITED",
    "EVENT_SIGNAL_GENERATED",
    "EVENT_STABILITY_ANALYZED",
    "EVENT_TRANSIENT_CHANGE",
    "FACT_BASELINE",
    "FACT_NETWORK",
    "FACT_PACKAGE",
    "FACT_PERMISSION",
    "FACT_PROCESS",
    "FACT_SIGNAL",
    "MIN_PERSISTENT_OBSERVATIONS",
    "RELATION_ASSOCIATED_WITH",
    "RELATION_OBSERVED_ON",
    "RELATION_OWNED_BY",
    "RELATION_RELATED_TO",
    "STABILITY_CATEGORIES",
    "STABILITY_MEANINGFUL",
    "STABILITY_TRANSIENT",
    "STABILITY_UNCERTAIN",
    "TRACKER_WINDOW",
    "AttributionState",
    "EntityStability",
    "EvidenceExplanation",
    "EvidenceFact",
    "InvestigationEvent",
    "Observation",
    "ObservationState",
    "ObservationTracker",
    "ProcessNode",
    "ProcessTree",
    "RelatedEntities",
    "SnapshotCompleteness",
    "SocketAttribution",
    "StabilityReport",
    "attribute_socket",
    "attribute_sockets",
    "baseline_category_completeness",
    "build_investigation_timeline",
    "build_process_tree",
    "classify_entity_state",
    "correlate_entity",
    "entity_stability_for",
    "explain_signal",
    "first_observed_by_key",
    "format_tree",
    "snapshot_completeness",
    "socket_table_completeness",
    "stabilize_drift",
]