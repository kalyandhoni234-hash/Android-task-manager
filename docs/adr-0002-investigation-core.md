# ADR-0002 — Investigation Core (stability, timeline, attribution, why-flagged, process tree)

Status: Accepted
Date: 2026-08-16

## Context

A real-device incident report showed the monitoring session producing many
INFO process changes between snapshots taken seconds apart. The root cause is
that the baseline diff compares two point-in-time reads and has no notion of
time: a short-lived kernel worker that exists in snapshot A but not snapshot B
is reported with the same weight as a permanently installed app. Detection is
therefore too sensitive to transient churn, and the report cannot answer the
natural follow-up questions:

* did the change persist, or was it a transient blip?
* what happened *before and after* the change?
* which process / package / socket owns which network activity?
* *why* was this flagged — what facts does the signal rest on?
* how does this process relate to the rest of the system (parent/child)?

## Decision

Add a GUI-independent `investigation` layer
(`src/android_task_manager/investigation/`) that treats every existing
monitoring artifact as evidence and derives:

1. **Stability (noise-resistant drift).** Raw diff → observation quality →
   temporal stability → meaningful drift. Each drift-check reads an
   observation of the process/socket set with a completeness grade
   (COMPLETE / PARTIAL / FAILED). PARTIAL snapshots can never produce a
   removal; an absence is meaningful only after ≥2 consecutive COMPLETE
   observations (`MIN_PERSISTENT_OBSERVATIONS = 2`, no hardcoded delays).
   Kernel/critical processes are not special-cased — they are judged by the
   same evidence. Packages are structural facts and pass through
   unstabilized, never re-classified.
2. **Timeline + correlation.** One deterministic event stream
   (T-001, T-002, …) covering baseline creation, drift, stability analysis,
   heuristics, signals and permission audits, with evidence references and
   related entities. Correlated entities resolve sockets to their owning
   processes by UID and processes to packages — only via the data, never by
   name matching that could fabricate a relationship.
3. **Attribution.** Socket → PID → process → package, reported honestly as
   FULL / PARTIAL / UNAVAILABLE. A socket with a UID is PARTIAL even when
   the process map is missing; UNAVAILABLE only when both the UID and the
   process are unknown. Nothing is ever zero-filled: unknown stays unknown.
4. **Why-flagged.** Every heuristic signal can be explained by deterministic
   evidence facts (baseline presence, CPU/memory, socket state, package
   attribution, owning process, stability classification). Facts are facts
   ("Socket was not present in baseline."), never verdicts.
5. **Process tree.** The parent/child hierarchy is built from collected
   PPIDs only. A missing parent is reported as unresolved — never inferred
   — and children are ordered by PID.

The incident layer consumes the investigation (`SCHEMA_VERSION = 2`):
with stability data, only meaningful drift becomes findings, transient and
unconfirmed changes appear on the timeline with their own event types, and
the report carries an `investigation` section with drift stability counts.
Without stability data the report behaves exactly like v1.

## Consequences

### Evidence-first, read-only, deterministic

Every aggregation in `investigation/` is a pure function over already
collected data — no ADB, no device writes, no worker threads. Identical
inputs produce identical output (fact ordering is deterministic everywhere).
The GUI only wires collected data into the new dialogs (timeline, process
tree, why-flagged).

### The no-fabrication invariant is preserved

None of the aggregations invent data: missing PPIDs → `None` (never
inferred), partial snapshots → UNCERTAIN/NOT_OBSERVED (never a removal),
unknown UIDs → no attribution claims, empty fact sets → the dialog says
"no evidence facts could be derived". The incident report's wording never
becomes a malware verdict.

### Schema evolution

`SCHEMA_VERSION = 2` adds the `investigation` section; consumers of v1
reports are unaffected (the section is optional and the v1 behavior is
preserved when stability data is absent).

### Test strategy

The behavior is pinned by fixture-driven tests (`tests/investigation_fixtures.py`,
`tests/test_investigation_*.py`) that require no device: scenarios cover
false-removal protection, persistent vs transient classification, single
absence, failed reads, PID reuse/name collisions, deterministic timelines,
honest partial attribution, explainable signals and unresolved parents.
GUI tests run offscreen.