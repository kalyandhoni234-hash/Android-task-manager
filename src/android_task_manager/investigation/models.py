"""Investigation core — data models for evidence-first analysis.

This package turns the existing monitoring output (baseline snapshots,
raw drift facts, heuristic signals) into a *stable, explainable
investigation workflow*:

* **Snapshot completeness** — every observation is COMPLETE, PARTIAL or
  FAILED, so absence is never claimed from an incomplete read.
* **Observation stability** — identities are classified STABLE /
  TRANSIENT / PERSISTENT / UNCERTAIN over a window of observations, and
  only stable evidence promotes a raw drift fact into *meaningful drift*.
* **Investigation timeline** — a unified, deterministic, chronological
  event log that references (never duplicates) evidence.
* **Event correlation** — packages, processes, sockets and signals joined
  by the existing identity vocabulary, with relationship words that never
  overclaim causation.
* **Network attribution** — socket → PID → process → UID → package, with
  an explicit FULL / PARTIAL / UNAVAILABLE honesty model.
* **Evidence explanation** — the "why was this flagged?" output, derived
  from actual collected data only.
* **Process tree** — a read-only parent/child view of one snapshot.

Like the rest of the pipeline, everything here is pure and read-only:
no ADB, no network, no writes, no verdicts. ``None`` means "unavailable"
and is never defaulted to zero or to a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..baseline.models import CHANGE_NEW, CHANGE_REMOVED
from ..process.models import ProcessCategory

# ---------------------------------------------------------------------------
# Snapshot completeness
# ---------------------------------------------------------------------------


class SnapshotCompleteness(Enum):
    """How trustworthy one category read of one observation is.

    * COMPLETE — the read fully succeeded; absence can be meaningful.
    * PARTIAL — the read produced data but is known to be incomplete;
      absence must not be claimed as removal.
    * FAILED — the read produced no usable data; nothing can be compared
      as though the set were empty.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Observation stability
# ---------------------------------------------------------------------------


class ObservationState(Enum):
    """Per-identity stability classification over an observation window.

    The spec's four core states plus the terminal confirmed-removal state:

    * STABLE — present in the baseline and still observed.
    * TRANSIENT — observed but not yet confirmed persistent (a change
      that appeared and vanished, or that only just appeared).
    * PERSISTENT — a new identity confirmed present across consecutive
      observations; also the state of a baseline identity whose absence
      is not yet confirmed.
    * UNCERTAIN — cannot be determined (e.g. the latest observation was
      partial or failed).
    * REMOVED — a baseline identity confirmed absent across repeated
      complete observations (meaningful removal).
    """

    STABLE = "stable"
    TRANSIENT = "transient"
    PERSISTENT = "persistent"
    UNCERTAIN = "uncertain"
    REMOVED = "removed"


@dataclass(frozen=True)
class Observation:
    """One identity-set observation of one category at one moment.

    ``timestamp`` is the collector's monotonic clock when available; the
    baseline-created observation carries ``None`` (no monotonic equivalent
    exists for it — ordering comes from the series, never from fabricated
    timestamps).
    """

    completeness: SnapshotCompleteness
    identities: frozenset[ProcessRef | PackageIdentity | SocketIdentity]
    timestamp: float | None = None


@dataclass(frozen=True)
class EntityStability:
    """The stability evidence for one identity key over a window.

    ``identity_key`` follows the existing diff-engine entity vocabulary: a
    process name, a package name, or ``"<protocol>:<addr>:<port>"``.
    """

    identity_key: str
    state: ObservationState
    observation_count: int
    consecutive_observations: int
    first_observed: float | None
    last_observed: float | None


#: Event buckets produced by the stability analysis (stable schema keys).
STABILITY_MEANINGFUL = "meaningful"
STABILITY_TRANSIENT = "transient"
STABILITY_UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class StabilityReport:
    """The stability classification of one category's raw drift facts.

    * ``events`` — every raw event that was classified (the inputs).
    * ``meaningful_events`` — promoted to meaningful drift (persistent
      new identities, confirmed removals, or categories without a
      stability analysis such as packages).
    * ``transient_events`` — observed but non-persistent; never promoted.
    * ``uncertain_events`` — could not be determined (incomplete reads).
    * ``entities`` — per-identity stability evidence.
    * ``summary`` — a deterministic, count-derived summary sentence.

    Nothing is silently destroyed: all raw events are kept in ``events``
    and the buckets partition it.
    """

    category: str
    events: tuple[DriftEvent, ...] = ()
    meaningful_events: tuple[DriftEvent, ...] = ()
    transient_events: tuple[DriftEvent, ...] = ()
    uncertain_events: tuple[DriftEvent, ...] = ()
    entities: tuple[EntityStability, ...] = ()
    summary: str = ""


# ---------------------------------------------------------------------------
# Investigation timeline + correlation
# ---------------------------------------------------------------------------

#: Live-timeline event types — the incident report vocabulary plus the
#: stability annotations. New keys are added here, never fabricated.
EVENT_BASELINE_CREATED = "BASELINE_CREATED"
EVENT_DRIFT_CHECKED = "DRIFT_CHECKED"
EVENT_DRIFT_EVENT = "DRIFT_EVENT"
EVENT_TRANSIENT_CHANGE = "TRANSIENT_CHANGE"
EVENT_NOT_OBSERVED = "NOT_OBSERVED"
EVENT_STABILITY_ANALYZED = "STABILITY_ANALYZED"
EVENT_HEURISTICS_EVALUATED = "HEURISTICS_EVALUATED"
EVENT_SIGNAL_GENERATED = "SIGNAL_GENERATED"
EVENT_PERMISSION_AUDITED = "PERMISSION_AUDITED"


@dataclass(frozen=True)
class InvestigationEvent:
    """One dated event on the unified investigation timeline.

    Events reference evidence by the existing identity vocabulary
    (``evidence_refs``) instead of embedding full snapshots. ``timestamp``
    is ``None`` only when the source carried no time — never fabricated.
    """

    event_id: str  # "T-001" — assigned after deterministic ordering
    event_type: str
    title: str
    description: str
    timestamp: datetime | None = None
    severity: str | None = None
    entity: str | None = None
    evidence_refs: tuple[str, ...] = ()
    related_entities: tuple[str, ...] = ()


#: Relationship vocabulary for correlation — relationship words only,
#: never causal language (RELATED_TO is safer than CAUSED_BY).
RELATION_RELATED_TO = "RELATED_TO"
RELATION_OWNED_BY = "OWNED_BY"
RELATION_ASSOCIATED_WITH = "ASSOCIATED_WITH"
RELATION_OBSERVED_ON = "OBSERVED_ON"


@dataclass(frozen=True)
class RelatedEntities:
    """Correlated entities for one entity key.

    Resolved through the current snapshot, the latest socket read and the
    heuristic report — using the existing identity vocabulary, never
    fabricated links.
    """

    entity: str
    relation: str = RELATION_RELATED_TO
    processes: tuple[ProcessRef, ...] = ()
    packages: tuple[PackageIdentity, ...] = ()
    sockets: tuple[SocketIdentity, ...] = ()
    signals: tuple[SuspiciousSignal, ...] = ()


# ---------------------------------------------------------------------------
# Network attribution
# ---------------------------------------------------------------------------


class AttributionState(Enum):
    """How far socket ownership attribution actually got.

    * FULL — socket → PID → process → package, all links resolved from
      collected data.
    * PARTIAL — socket → UID (optionally UID → package). UID-level
      attribution is never labeled package-level.
    * UNAVAILABLE — no reliable owner was collected.
    """

    FULL = "full"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SocketAttribution:
    """Ownership attribution for one socket, honestly labeled.

    On non-root Android the socket tables expose a UID but no PID, so
    real-device rows typically land in PARTIAL — FULL is only claimed
    when every link exists in the collected data.
    """

    socket: SocketIdentity
    attribution_state: AttributionState
    pid: int | None = None
    process_name: str | None = None
    uid: int | None = None
    package_names: tuple[str, ...] = ()
    baseline_status: str = "BASELINE"
    first_observed: float | None = None


# ---------------------------------------------------------------------------
# Evidence explanation ("why was this flagged?")
# ---------------------------------------------------------------------------

#: Evidence-fact categories (stable keys).
FACT_BASELINE = "baseline"
FACT_PROCESS = "process"
FACT_NETWORK = "network"
FACT_PACKAGE = "package"
FACT_PERMISSION = "permission"
FACT_SIGNAL = "signal"


@dataclass(frozen=True)
class EvidenceFact:
    """One traceable fact supporting a signal.

    ``text`` is a fact, never a judgment ("Socket was not present in
    baseline"), and ``reference`` is the entity key or evidence row the
    fact is derived from.
    """

    category: str
    text: str
    reference: str | None = None


@dataclass(frozen=True)
class EvidenceExplanation:
    """The deterministic "why was this flagged?" explanation.

    Facts are derived from actual collected data (baseline snapshots,
    process samples, socket tables, package map, audits, the signal
    itself) — no LLM, no GUI-text scraping, no verdicts.
    """

    signal: SuspiciousSignal
    headline: str
    facts: tuple[EvidenceFact, ...] = ()


# ---------------------------------------------------------------------------
# Process tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessNode:
    """One node of the read-only process hierarchy.

    ``ppid`` is ``None`` when the collector could not provide a parent;
    ancestry is never inferred. ``children`` are the direct children
    present in the same snapshot, ordered by PID.
    """

    pid: int
    name: str
    uid: int | None
    ppid: int | None
    category: ProcessCategory
    children: tuple["ProcessNode", ...] = ()


@dataclass(frozen=True)
class ProcessTree:
    """A read-only parent/child view of one process snapshot.

    * ``roots`` — nodes whose parent is unknown or not in the snapshot.
    * ``unresolved_parents`` — PIDs whose parent PID is not in the
      snapshot; the parent is reported as unavailable, never inferred.
    """

    timestamp: float
    nodes: tuple[ProcessNode, ...] = ()
    roots: tuple[ProcessNode, ...] = ()
    unresolved_parents: tuple[int, ...] = ()

    def node(self, pid: int) -> ProcessNode | None:
        """The node with *pid*, or ``None`` when it is not in the tree."""
        return next((n for n in self.nodes if n.pid == pid), None)


__all__ = [
    "ATTRIBUTION_STATES",
    "AttributionState",
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
    "EntityStability",
    "EvidenceExplanation",
    "EvidenceFact",
    "FACT_BASELINE",
    "FACT_NETWORK",
    "FACT_PACKAGE",
    "FACT_PERMISSION",
    "FACT_PROCESS",
    "FACT_SIGNAL",
    "InvestigationEvent",
    "Observation",
    "ObservationState",
    "ProcessNode",
    "ProcessTree",
    "RELATION_ASSOCIATED_WITH",
    "RELATION_OBSERVED_ON",
    "RELATION_OWNED_BY",
    "RELATION_RELATED_TO",
    "RelatedEntities",
    "STABILITY_MEANINGFUL",
    "STABILITY_TRANSIENT",
    "STABILITY_UNCERTAIN",
    "SnapshotCompleteness",
    "SocketAttribution",
    "StabilityReport",
    "SuspiciousSignal",
]

#: Re-exported by the package for convenience (kept in lockstep with the
#: baseline vocabulary).
ATTRIBUTION_STATES = ("full", "partial", "unavailable")