# ADR-0005 — Advanced Performance & Root-Cause Intelligence (v0.9.0)

Status: Accepted
Date: 2026-08-21

## Context

v0.8.1 ships Background User Apps: the monitor already publishes CPU, memory,
battery, storage and (via the Background User Apps pipeline) per-application
load snapshots on its single existing ``QTimer`` ``tick()``. There is no
second collection loop, no second action executor, and no analysis layer that
turns those snapshots into *evidence* and *findings*.

The v0.9.0 goal is Advanced Performance & Root-Cause Intelligence: turn the
existing time-series into explainable, traceable performance facts — windows,
baselines, threshold occupancy, sustained conditions, process pressure and
application pressure — without inventing new metrics, new polling, or new
device-control paths.

This ADR covers **Phases 1, 2 and 3**: the Qt-independent analysis *domain*
(Phase 1), its wiring to the existing ``MonitorWorker`` snapshot pipeline via a
thin Qt adapter (Phase 2), and the user-facing Performance Intelligence surface
(Phase 3). No new monitor loop, no new action executor, no release.

## Decision

Introduce a new GUI-independent, deterministic package
``src/android_task_manager/performance/`` with a strict reuse policy:

* ``models.py`` — ``PerformanceSample`` (one timestamped multi-metric
  observation), ``PerformanceEvidence`` (one literal, traceable fact),
  ``EvidenceKind``, ``PerformanceMetric``; it **re-exports**
  ``DiagnosticFinding`` / ``DiagnosticSeverity`` / ``DiagnosticCategory`` from
  :mod:`android_task_manager.diagnostics.models` (the finding contract is
  reused, never redefined).
* ``window.py`` — ``PerformanceWindow``: a bounded, multi-metric observation
  window that delegates all min/max/avg/trend/peak math to the existing
  :class:`android_task_manager.history.metrics.MetricHistory` (one per
  metric). It adds only two window-level quantities history lacks: threshold
  *occupancy* and *change-from-baseline*.
* ``baseline.py`` — ``Baseline`` + ``BaselineCalculator``: median, p95 and
  stddev via the stdlib ``statistics`` module, built on top of the shared
  ``MetricStats`` so the baseline mean equals the live-window average.
* ``evidence.py`` — deterministic, single-place evidence sentence builders.
  Every statement is a literal restatement of observed numbers; none asserts a
  cause.
* ``events.py`` — ``PerformanceEvent`` (normalized, typed) and a single
  ``to_timeline_event`` adapter to the existing
  :class:`android_task_manager.timeline.models.TimelineEvent`. The Timeline is
  **not** modified to consume performance events directly; adaptation happens
  in one function.
* ``session.py`` — ``PerformanceSession``: reuses
  :class:`android_task_manager.history.session.SessionHistory` for the four
  canonical live metrics (including its device-scoped ``begin_session`` /
  ``clear`` reset) and a ``PerformanceWindow`` for the extended metrics
  (process count, network throughput). It owns no timer, no ADB, no Qt.
* ``analyzer.py`` — ``PerformanceAnalyzer``: pure functions
  (``analyze_cpu`` / ``analyze_memory`` / ``analyze_storage`` /
  ``analyze_process_pressure`` / ``analyze_application_pressure``) that produce
  ``PerformanceEvidence`` always, and a ``DiagnosticFinding`` only when an
  explicit, evidence-backed threshold rule is satisfied. Thresholds reuse
  :mod:`android_task_manager.diagnostics.thresholds`; the recommended action
  points at the existing, verified action vocabulary (``force_stop``) as an
  *investigation* step — never an automatic destructive act.

One additive, backward-compatible change to a shared model:
``DiagnosticCategory.PROCESS = "process"`` is added so process-pressure
findings are categorized honestly instead of being mis-filed under CPU.

## Reused components (explicit, no re-implementation)

| Need | Reused from | How |
| --- | --- | --- |
| Bounded per-metric window, min/max/avg/trend, peak, sustained | ``history.metrics.MetricHistory`` / ``MetricStats`` / ``TrendDirection`` | ``PerformanceWindow`` wraps one ``MetricHistory`` per metric |
| Per-device session reset semantics | ``history.session.SessionHistory`` | ``PerformanceSession.canonical`` |
| Finding contract | ``diagnostics.models.DiagnosticFinding`` | re-exported and produced verbatim |
| Severity / category vocabulary | ``diagnostics.models.DiagnosticSeverity`` / ``DiagnosticCategory`` | used directly |
| Threshold values | ``diagnostics.thresholds`` | aliased into the analyzer defaults |
| Unified event log | ``timeline.models.TimelineEvent`` | adapted via ``to_timeline_event`` |
| Action vocabulary (no new executor) | ``action.capability.FORCE_STOP`` | referenced in recommended actions only |
| Application identity | v0.8.1 Background User Apps pipeline | caller resolves; analyzer consumes ``(package, label, cpu, mem)`` |

## Anti-duplication rules (enforced by tests)

* No module in ``performance/`` imports ``PySide*``, ``QTimer``,
  ``MonitorWorker``, ``QWidget``/``Qt*``, or ``subprocess``. A source-level
  test asserts this.
* ``MetricHistory`` statistics are never reimplemented; ``PerformanceWindow``
  and ``Baseline`` compose them.
* Identity resolution (process→UID→package→label) is **never** performed in
  ``performance/``; the analyzer receives already-resolved application loads.
* There is exactly one action executor in the project (``action/`` +
  ``gui/action_worker.py``); the analyzer only names actions, it never runs
  them.

## Safety invariants

* **No new polling.** No ``QTimer``, no ``MonitorWorker``, no process loop is
  added anywhere in v0.9. The monitor's single ``tick()`` remains the only
  collection path; the GUI feeds ``PerformanceSession.record(...)`` from the
  snapshots it already publishes.
* **No fabricated metrics.** ``None``/unavailable values are never recorded or
  guessed; empty inputs yield empty analyses.
* **No fabricated causes.** ``DiagnosticFinding.what/why/evidence`` repeat the
  observed numbers; a test rejects speculative wording ("because", "leak",
  "root cause", "likely caused", "probably due").
* **No auto-destructive action.** Findings recommend investigation via the
  existing action panel; nothing is force-stopped, disabled or uninstalled by
  the analysis layer.
* **v0.8.1 baseline intact.** This phase does not bump the version, tag, push
  or release. The ``v0.8.1`` tag and the Background User Apps feature are
  untouched except for the additive ``DiagnosticCategory.PROCESS`` member
  (source-only, backward-compatible).

## Consequences

* The analysis domain is fully testable without a device, a sleep, or a GUI
  (28 deterministic tests added), satisfying the project's no-fabrication and
  determinism invariants.
* Future phases (GUI panels, Timeline wiring, report integration) consume the
  already-typed ``PerformanceSample`` / ``PerformanceEvidence`` /
  ``PerformanceEvent`` objects; they add presentation, not new analysis logic.
* ``PerformanceSession`` is the single sink the GUI must feed, keeping the
  monitor-loop contract unchanged.

## Phase 2 — MonitorWorker integration (thin Qt adapter)

Phase 1's domain is fed by the GUI through **one** new, GUI-facing object:
``gui/performance_integration.py`` → :class:`PerformanceIntegration` (the only
performance module that imports ``PySide6``). It adds **no** input signal, **no**
timer, and **no** worker — it subscribes to the monitor's *existing* signals and
forwards them to the pure :class:`PerformanceOrchestrator`.

### Signal mapping (reused, not new)

| Monitor signal (existing) | Adapter slot | Forwards to |
| --- | --- | --- |
| ``MonitorWorker.snapshots(c, m, p, b, net)`` | ``on_snapshots`` | ``orchestrator.ingest(cpu, memory, processes, battery, network)`` |
| ``MonitorWorker.storage_snapshot`` | ``on_storage`` | ``orchestrator.ingest(storage=...)`` |
| ``MonitorWorker.foreground_snapshot`` | (ignored for perf) | — |
| v0.8.1 ``BackgroundAppsSnapshot`` (already identity-resolved) | ``on_background_apps`` | ``orchestrator.set_background_apps`` + ``ingest(background_apps=...)`` |
| ``MonitorWorker.serial_ready`` | ``on_serial_ready`` | ``orchestrator.begin_session(serial)`` |
| ``MonitorWorker.connection_changed`` | ``on_connection_changed`` | ``begin_session`` on connect / ``end_session`` on disconnect |

The adapter re-publishes domain output on three output ``Signal`` s
(``evidence_ready`` / ``findings_ready`` / ``events_ready``); the dashboard
consumes them later (Phase 3+). It performs no ADB, no subprocess, and never
touches a widget.

### Orchestrator (pure, Qt-independent)

``performance/orchestrator.py`` → :class:`PerformanceOrchestrator` ties the
domain together: on every ``ingest`` it (1) records the sample into its owned
``PerformanceSession``, (2) runs the five analyzers on the live windows, and
(3) feeds each produced finding through the :class:`ConditionTracker` to obtain
a stable lifecycle. Result = :class:`OrchestratorResult` (evidence, findings,
events). It exposes ``begin_session`` / ``end_session`` (which resets the
tracker) and ``set_background_apps`` (cached for the next analysis).

### Metric derivation (reused verbatim from the dashboard/health path)

* CPU = ``cpu.aggregate_utilization_percent``
* memory = ``(total - available) / total * 100``
* battery = ``battery.level_percent``
* storage = ``storage.used_percent``
* process_count = ``len(processes.processes)``
* network = ``network.aggregate_throughput.{rx,tx}_bytes_per_sec``
* application load = ``BackgroundAppsSnapshot`` entries (resolved package, label,
  ``cpu_percent``, ``memory_percent``)

### Finding deduplication — ``ConditionTracker``

A finding is keyed ``f"{category}:{severity}"`` (e.g. ``cpu:critical``). The
tracker maintains exactly one :class:`ActiveCondition` per key and emits:

* ``STARTED`` — first time the condition appears (after ``min_samples``).
* ``ACTIVE`` — while sustained, **throttled to one event per 60 s** to prevent
  timeline spam.
* ``RECOVERED`` — when the condition clears for ``min_samples`` consecutive
  samples (no fabricated "still bad" re-assertions).

The orchestrator emits at most **one** finding object per *started* condition
per ingest (a later sustained finding is not re-emitted; the ACTIVE throttling
applies only to timeline events), satisfying the "no event spam" test.

### Event lifecycle → Timeline

Each ``PerformanceEvent`` is adapted once via ``events.to_timeline_event`` and
recorded on the existing :class:`android_task_manager.timeline.engine.EventTimeline`
(the Timeline model is unchanged; adaptation remains a single function). Event
types: ``DEGRADATION_STARTED`` / ``DEGRADATION_ACTIVE`` / ``RECOVERED`` /
``ANOMALY``.

### Application correlation (no identity re-resolution)

:func:`translation.app_loads_from_background` consumes the v0.8.1-resolved
``BackgroundAppsSnapshot`` and feeds ``analyze_application_pressure`` with
``(package_name, label, cpu_percent, memory_percent)``. ``performance/`` still
performs **no** process→UID→package→label resolution.

### Tests added (Phase 2)

``tests/test_performance_integration.py`` (14 tests) covers: canonical metric
ingestion + session re-use, missing-metric honesty (``None`` recorded as empty,
not guessed), process + application pressure correlation, finding
deduplication (STARTED once, RECOVERED once), ACTIVE-event throttling (no spam),
and a source-level assertion that ``performance/`` imports no ``PySide*``,
``QTimer``, ``MonitorWorker``, ``subprocess`` or ``adb``. Full suite: 1828
passed; ruff + mypy clean for ``performance/`` and the adapter.

## Phase 3 — Performance Intelligence surface (presentation)

Phase 3 adds the user-facing surface that renders the engine's output. It is
**presentation only**: the GUI never re-derives analysis. A single, pure,
Qt/ADB-free :class:`~android_task_manager.performance.view.PerformanceViewState`
(assembled by ``PerformanceOrchestrator.view_state()``) is the *only* object the
GUI reads. The orchestrator joins the session, baseline, tracker, analyzer and
the retained last evidence/events/history into one render-ready snapshot; the
window keeps **no parallel performance caches**.

### View-state model (``performance/view.py``)

``PerformanceViewState`` carries the answers to the six Phase 3 questions:

* ``overall_state`` — NORMAL / CPU / MEMORY / STORAGE / PROCESS / APPLICATION /
  MULTI_METRIC / RECOVERING (RECOVERING within ``RECOVERING_WINDOW_S`` of a
  recovery; the device need not re-baseline after a transient breach).
* ``metrics`` — one :class:`MetricView` per canonical metric (CPU, Memory,
  Storage, Battery) with current value, ``Baseline`` (median/p95/stddev/count),
  delta-from-baseline, threshold *occupancy* (how far into the warn→crit band the
  current reading sits), and a ``condition`` (NORMAL / ELEVATED / CRITICAL /
  UNKNOWN). Battery's thresholds come from the top-level
  ``android_task_manager.thresholds`` (not the diagnostics thresholds).
* ``findings`` — active :class:`FindingView` (severity, category, evidence,
  phase, first/last seen).
* ``evidence`` — typed :class:`EvidenceRow` grouped into observed / threshold /
  baseline / change / correlated activity.
* ``app_correlations`` — :class:`AppCorrelation` rows built **only** from the
  already-resolved ``BackgroundAppsSnapshot`` identity (package → label →
  cpu/memory/process-count). They are correlation, never attribution: the UI
  shows "active during the pressure window", never "caused by".
* ``events`` — lifecycle STARTED / ACTIVE / RECOVERED transitions. The tracker
  emits transitions only, so each ``ingest`` overwriting the list would erase an
  earlier STARTED on a steady-state tick; the orchestrator therefore *accumulates*
  (bounded to 50) and clears them on ``end_session`` (disconnect).
* ``history`` — bounded per-metric sample series feeding the history plots.

### Widgets (``gui/performance_page.py``)

* :class:`PerformancePage` — the standalone sidebar destination
  (``performance`` / index 10). It renders: an overall-state badge; four metric
  cards (current / baseline / delta / occupancy / condition / evidence); the
  active-findings list; the grouped evidence panel; the application-correlation
  rows; reused :class:`HistoryPlotWidget` plots; the lifecycle-events list; and a
  "View in Timeline" button (emits ``view_timeline_requested`` → Intelligence
  page). Distinct states stay distinct: disconnected → "DEVICE DISCONNECTED"
  with no fabricated cards; connected-but-collecting → "Collecting baseline…".
* :class:`PerformanceSummaryWidget` — a compact widget embedded in the existing
  **Intelligence** page (immediately after DEVICE HEALTH). It shows the same
  ``overall_state`` badge, a one-line metric summary and the active-finding
  count, with a "View Performance" button (emits ``performance_requested`` →
  full page). Both widgets render the *same* ``view_state`` snapshot; the window
  feeds them together in ``_refresh_performance_page``.

### Wiring in ``MainWindow``

* The page and summary widget are created in ``__init__``; the sidebar already
  lists ``PERFORMANCE``; the Intelligence page gained a PERFORMANCE INTELLIGENCE
  section.
* The three adapter handlers (``_on_performance_findings`` /
  ``_on_performance_evidence`` / ``_on_performance_events``) simply call
  ``_refresh_performance_page``. That method reads ``orchestrator.view_state()``
  (the single source of truth) and renders **both** the standalone page and the
  Intelligence summary — removing the earlier per-id evidence/event GUI caches.
* ``_on_performance_events`` still records each transition on the unified
  :class:`EventTimeline` via the shared ``to_timeline_event`` adapter (the
  Timeline model is untouched) — this is the only place performance events touch
  the timeline, and it reuses the existing adapter (no new recording path).
* On disconnect, ``end_session`` resets the tracker and clears the view state's
  evidence/events/background-history; the page re-renders the disconnected state.
  No new timer, signal, or worker is introduced.

### Reused components (explicit)

| Need | Reused from |
| --- | --- |
| Findings card shape / tokens | ``gui/diagnostics_page`` + ``styles.py`` |
| Sidebar + page-stack navigation | existing ``Sidebar`` / ``QStackedWidget`` pattern |
| History plots | ``gui/widgets/history_base.HistoryPlotWidget`` |
| Unified event log | ``timeline`` + ``to_timeline_event`` adapter |
| App identity (no re-resolution) | ``BackgroundAppsSnapshot`` (existing pipeline) |
| Active-condition set | ``ConditionTracker`` (orchestrator-owned) |

### Tests added (Phase 3)

* ``tests/test_performance_view_state.py`` (3 domain tests) — the orchestrator's
  ``view_state`` detects CPU pressure + correlates the resolved app, lifecycle
  events *accumulate* across steady-state ticks (the overwrite bug it prevents),
  and ``end_session`` clears the surface.
* ``tests/test_performance_page.py`` (18 GUI tests, A–Q) — page creation,
  disconnected / collecting / normal states, per-metric pressure badges, grouped
  evidence (no duplicate per stable id), baseline + occupancy display, insufficient
  baseline → "Collecting baseline…", application correlation (no "caused by"
  wording), package fallback, lifecycle events, reconnect clearing stale state,
  an architecture assertion that the presentation layer contains no
  ``QTimer`` / ``MonitorWorker(`` / ``subprocess.`` / ``adb shell``, the
  Intelligence page gaining the performance section, and the summary widget.

Full suite after Phase 3: 1849 passed; ruff + mypy clean for ``performance/``,
the adapter, and the page.

## Phase 4 — Explainable Performance Intelligence

Phase 4 turns the Phase 1–3 evidence surface into a transparent *explanation*
layer that answers "why this is happening" without ever asserting a root cause.
All intelligence is produced in ``performance/`` (pure); the GUI only renders
``PerformanceViewState``.

### Components added (all pure, deterministic, Qt/ADB-free)

* **Baseline deviation** (``performance/deviation.py``) — ``compute_deviation``
  compares the live reading to the Phase 1 ``Baseline`` and classifies a
  ``band`` (``NORMAL`` / ``ELEVATED`` / ``CRITICAL`` / ``UNKNOWN``) from the
  fixed thresholds. Statistical deltas (``absolute_delta``, ``percentage_delta``,
  ``z_score``) are only populated when the baseline has ``>= 2`` samples
  (``_MIN_DEVIATION_SAMPLES``); otherwise ``sufficient=False`` and the band still
  reflects the threshold. Battery uses ``higher_is_worse=False``. A ``None`` or
  zero-median baseline yields ``percentage_delta=None`` (no divide-by-zero).
  Deviations exist for cpu/memory/storage/battery; process count has **no**
  baseline (band is computed from the process thresholds only).
* **Deterministic score** (``performance/score.py``) — ``compute_score`` maps
  each metric's band to a penalty share of ``DEFAULT_MAX_PENALTIES``
  (cpu 25 / memory 25 / storage 20 / process 15 / battery 15), weight
  ``NORMAL``/``UNKNOWN = 0``, ``ELEVATED = 0.5``, ``CRITICAL = 1.0``. Each
  component contribution is rounded, then summed from 100 and clamped to
  ``[0, 100]``. The result is ``PerformanceScore(score, components, sufficient)``.
  Identical inputs always yield the same score.
* **Trend classification** (``performance/trend.py``) — ``classify_trend``
  compares the mean of the first and second halves of the window and returns
  ``STABLE`` / ``IMPROVING`` / ``DEGRADING`` / ``RECOVERING`` /
  ``INSUFFICIENT_DATA``. ``RECOVERING`` is ``IMPROVING`` whose latest sample is
  at or above a ``recovering_reference`` (the warn threshold). Fewer than
  ``min_samples=4`` values yields ``INSUFFICIENT_DATA``.
* **Non-causal contributors** (``performance/contributors.py``) —
  ``rank_contributors`` takes the already-resolved ``BackgroundAppsSnapshot``
  (never re-resolved) and ranks entries by observed cpu+memory load during the
  window. It reports ``relevant_metric`` (cpu/memory/process, chosen only from
  the metrics already under pressure), a load share as ``confidence``, and an
  explicit ``reason`` that says "observed … contributor associated with the
  current pressure window". Entries with no package, in ``excluded``, or with no
  observable load are dropped. Identity is the snapshot's own package/label;
  process count uses ``len(pids)`` (there is no separate count field).
* **Explanation + recommendations** (``performance/explanation.py``) —
  ``build_explanation`` assembles deterministic ``observed`` bullet points, a
  non-causal ``interpretation``, the top contributors, and
  ``investigation_recommendations`` via ``build_recommendations``. The text is
  built strictly from the literal values it is given; it never contains
  "caused"/"responsible"/"definitely malicious"/"force-stop"/"kill".
  Recommendations are investigation-only ("Inspect … details") and never an
  automatic destructive action — the existing v0.7 action capability remains
  the sole gate and is not invoked here.

### View-state extension

``PerformanceViewState`` gains ``performance_score``, ``metric_deviations``,
``trends``, ``contributors``, ``explanations`` and
``investigation_recommendations`` (all defaulted so Phase 3 callers are
unaffected). The orchestrator's ``view_state`` populates them from the same
session/window it already builds the Phase 3 fields from — no new polling, no
new metrics.

### UI (Phase 4H)

``gui/performance_page.py`` adds a "PERFORMANCE HEALTH nn/100" badge and a
"Why this is happening" section rendering, per active condition: the observed
bullets, the interpretation, the top observed contributors, and a
"RECOMMENDED INVESTIGATION" list. ``PerformanceSummaryWidget`` also shows the
health score. Honesty rules are unchanged: unavailable values render as ``—``,
and application rows remain *correlation*.

### Safety boundaries (non-negotiable)

* No causal claim, no fabricated identity/metric, no auto-destructive action.
* System/protected apps are excluded via the ``excluded`` set; unknown identity
  is never fabricated and simply shows the package name.
* Disconnect and ``end_session`` clear the surface; no extra timeline spam.
* No new ``QTimer`` / ``MonitorWorker`` / ``subprocess`` / ADB, and no second
  inventory or APK label-resolution loop.

### Tests added (Phase 4)

* ``tests/test_performance_explanation.py`` (20 pure tests) — deviation bands
  (normal/critical/insufficient-baseline/zero-median, battery lower-is-worse),
  deterministic score (critical+elevated, all-critical=0, all-normal=100),
  trend classification (all five outcomes), contributor ranking (order,
  exclusion, missing-label fallback), explanation text containing no causal
  language, investigation-only recommendations, and an orchestrator
  ``view_state`` smoke test asserting the new fields populate. It also asserts
  the ``performance/`` layer contains no ``QTimer`` / ``MonitorWorker(`` /
  ``import subprocess`` / ``import adb``.
* Phase 3 UI tests in ``tests/test_performance_page.py`` continue to pass
  (the new section renders conditionally and defaults safely).

### Validation status

The full existing suite (1849) plus the new Phase 4 tests pass; ``ruff`` and
``mypy`` are clean for ``performance/``. Version remains **0.8.1** — no
``__version__`` bump, no git tag, no push, no release. Phase 4 is complete;
Phase 5 is deferred.

## Phase 5 — Historical Performance & Investigation Episodes

Phase 5 turns the live condition lifecycle (Phase 1–3) and the explanation
layer (Phase 4) into **episode history**: a recoverable, device-scoped record
of every performance condition's start, peak, duration and recovery, with a
deterministic comparison against the live ``Baseline`` and against *previous
episodes of the same metric*, plus a structured, non-causal investigation
summary. All intelligence is produced in ``performance/`` (pure); the GUI only
renders ``PerformanceViewState``.

### Components added (all pure, deterministic, Qt/ADB-free)

* **Episodes** (``performance/episodes.py``) — ``PerformanceEpisode`` captures
  ``condition_key``, ``category``, ``severity``, ``metric``, ``started_at``,
  ``recovered_at``, ``is_active``, ``peak_value``, ``peak_timestamp``,
  ``current_value``, ``baseline_p95`` (from ``BaselineCalculator.from_window``,
  ``None`` if the window is empty), ``peak_vs_baseline_p95_pp`` (``None`` when
  either side is missing), ``duration`` (``None`` defensively if
  ``started_at``/``recovered_at``/``current_time`` are ``None`` or the span is
  non-positive), ``contributor_correlation`` (per-episode, built from the
  orchestrator's retained background history) and ``background_history``.
  ``build_episode`` derives ``peak_value``/``peak_timestamp`` **only** from
  real recorded samples (it never synthesizes), falls back to the live reading
  when no samples exist, and is total-order comparable by ``(started_at,
  condition_key)`` so episodes sort deterministically.
* **Historical comparison** (``performance/history_compare.py``) —
  ``HistoricalComparison`` answers *"worse than before?"* non-causally.
  ``build_historical_comparison`` always provides the live ``peak_vs_baseline_pp``
  delta; the *comparable-episodes* comparison is gated on **sufficient data**:
  a baseline must be available **and** at least one previous same-metric
  episode must exist. When insufficient, ``sufficient=False`` and ``message``
  is the literal ``HISTORICAL_DATA_INSUFFICIENT`` (the sentinel constant
  ``INSUFFICIENT``) — never a fabricated verdict. ``find_comparable`` returns
  prior episodes of the same metric (excluding the current one, ordered
  newest-first). The summary text avoids causal wording ("prior episodes").
* **Contributor correlation** (``performance/episodes.py`` reuses
  ``contributors.rank_contributors``) — per-episode correlation is computed over
  the orchestrator's retained ``_background_history`` window (the v0.8.1
  identity-resolved ``BackgroundAppsSnapshot``; **never** re-resolved).
  ``correlate_contributors`` reports ``samples_present``/``samples_total``,
  ``times_top`` (how often an app sat at the top of the relevant load during
  pressure), drops empty/``excluded``/unobservable entries, and falls back to
  the package name when a label is missing. It is correlation, not attribution.
* **Investigation summary** (``performance/investigation.py``) —
  ``InvestigationSummary`` packages the episode into ``status``
  (``ACTIVE``/``RECOVERED``), ``peak_value``/``peak_timestamp``,
  ``baseline_p95``, ``peak_vs_baseline_p95_pp``, ``duration_text``
  (``format_duration``), ``top_contributor`` and ``evidence_bullets``. The
  bullets restate the literal numbers (peak, baseline delta, duration, top
  observed contributor) and never use "caused"/"causing"/"responsible"/
  "definitely malicious"/"force-stop"/"kill". It is built deterministically
  (identical inputs → identical object) and consumed verbatim by the UI.

### Orchestrator wiring (no new polling)

``PerformanceOrchestrator`` gains two retained, device-scoped buffers:
``_background_history`` (capped 600; appended on each ``ingest`` that carries a
``BackgroundAppsSnapshot``) and ``_recovered`` (the conditions the
``ConditionTracker`` declared recovered). ``end_session`` (disconnect/device
switch) clears **both**, so a reconnect can never resurrect the previous
device's episodes. ``view_state`` now also builds, for the current condition
key, ``active_episodes`` / ``recent_episodes`` / ``episode_count`` /
``current_episode`` (via ``_build_episodes`` / ``_episode_from_condition`` /
``_baseline_for``), ``investigation_summary`` and ``historical_comparison``.
Episodes are derived entirely from the existing session window and the
recovered-condition set; no second timer, worker or inventory loop is added.

### View-state extension

``PerformanceViewState`` gains ``active_episodes``, ``recent_episodes``,
``episode_count``, ``current_episode``, ``investigation_summary`` and
``historical_comparison`` (all defaulted so Phase 3/4 callers are unaffected).

### UI (Phase 5J/K)

``gui/performance_page.py`` adds a "Performance episodes" section with a card
per active/recent episode (status, peak vs baseline, duration, top observed
contributor) rendering through the same ``PerformanceViewState`` snapshot;
disconnected state clears it. ``gui/intelligence_page.py`` gains a "LATEST
PERFORMANCE EPISODE" summary line. ``gui/styles.py`` adds the
``perfEpisodeCard`` / ``perfEpisodeSummary`` tokens, reusing the existing
diagnostics card language — no new widget library.

### Safety boundaries (non-negotiable)

* No causal claim: all historical/summary text describes observed ordering and
  values, never a cause. The architecture test asserts ``performance/`` imports
  no ``QTimer`` / ``MonitorWorker(`` / ``subprocess.`` / ``adb`` and no
  ``PySide6``.
* No fabricated identity/metric: contributor correlation consumes only the
  already-resolved snapshot; ``None``/missing values render as ``—``.
* No auto-destructive action: the investigation summary recommends
  inspection only; the v0.7 action layer is unchanged.
* No extra timeline spam: episodes are a presentation of the existing
  lifecycle; ``end_session`` clears state so a reconnect cannot resurrect stale
  episodes.

### Tests added (Phase 5)

* ``tests/test_performance_episodes.py`` (34 pure + GUI tests) — lifecycle
  (started/active/recovered; simultaneous independent cpu+memory episodes),
  peak detection from real samples, defensive duration (missing/non-monotonic/
  negative spans), baseline + historical comparison (sufficient vs
  ``HISTORICAL_DATA_INSUFFICIENT``), comparable-episode median, per-metric
  episodes (cpu/memory/storage/process), contributor correlation (frequency,
  repeated top, missing-label fallback, unknown-identity + system exclusion),
  investigation summary (content, determinism, no causal wording), view-state
  integration, GUI rendering (active + recovered + disconnect clearing),
  reconnect-not-resurrecting, timeline STARTED-event dedup, a Phase 1–4
  regression smoke test, and the architecture/honesty audit (no forbidden
  capability in ``performance/``, no ``PySide6`` import, disconnect clears
  device-bound state).

### Validation status

Full suite: **1903 passed**. ``ruff check src tests`` clean; ``mypy`` clean for
``performance/`` (20 source files). Version remains **0.8.1** — no
``__version__`` bump, no git tag, no push, no release. Phase 5 is complete;
later phases (Timeline episode wiring, report integration, multi-episode
history UI) remain deferred.

## Phase 5b — Grouped Performance Episodes

The per-condition episodes above answer *"what happened to one condition?"*.
Phase 5b adds the coherent incident view: **every overlapping pressure
condition belongs to ONE bounded episode**, so CPU + memory breaching
together is a single incident — never "Episode #1 = CPU, Episode #2 =
Memory".

### Episode semantics

An episode represents one coherent performance incident:
*"something happened during this period, these conditions were involved,
this was the severity/score impact, these applications were observed as
contributors, and the device eventually recovered."*

### Condition grouping — ``performance/episode_tracker.py`` (NEW)

:class:`EpisodeTracker` is a pure domain component fed the already-normalized
:class:`~android_task_manager.performance.tracker.TrackerStep` transitions on
each monitor tick (it does **not** re-implement per-tick detection):

* **Start** — the first metric-pressure condition transition opens episode
  ``P-001``.
* **Continuation** — while open, further conditions join the *same* episode;
  affected metrics accumulate in first-appearance order; severity escalates
  monotonically to the highest level observed; evidence accumulates under a
  bounded retention rule; contributors refresh from already-resolved
  snapshots (a snapshot-less tick never wipes them); the Phase 4 score
  trajectory (start / min / recovery / delta) is recorded from
  ``compute_score``, computed once per tick via the shared
  ``_deviations_snapshot()``.
* **Recovery** — a member recovering removes it from *active membership*
  only; involved conditions/metrics stay listed. The episode becomes
  ``RECOVERED`` only when membership is empty, preserving start, end,
  duration, conditions, metrics, evidence, contributors, severity and score.
* **Non-overlap** — after closure the next unrelated condition starts a new
  episode (``P-002`` …); windows are never merged across a recovery.

Application-pressure findings are excluded from membership: they are emitted
unconditionally while background apps are monitored (informational "top
application load"), so treating them as episode-forming would prevent any
episode from ever recovering. They remain correlation context (findings,
events, contributor ranking).

### Deterministic identity & ordering

Ids are ``P-NNN`` assigned per session (no random UUIDs) and reset on
``end_session``/reconnect, so stale device-bound episodes can never resurrect
or collide. Rendering order is deterministic: the open episode first, then
completed episodes newest-first.

### Retention

Completed episodes are capped (``EPISODE_RETENTION = 20``) and per-episode
evidence is capped (``EVIDENCE_RETENTION = 24``, deduplicated by evidence id)
— consistent with the layer's other bounded buffers.

### Timeline behavior

No new timeline path: the ConditionTracker's existing throttled
STARTED / ACTIVE / RECOVERED events **are** the episode's lifecycle stream
(a sustained 30-tick incident still yields exactly one STARTED event).
Episodes surface through ``PerformanceViewState``
(``current_episode`` / ``active_episodes`` / ``recent_episodes`` /
``episode_count``), not through per-tick events.

### Model extension

``PerformanceEpisode`` (``performance/episodes.py``) gains defaulted grouped
fields — ``episode_id``, ``condition_keys``, ``metrics``,
``lifecycle`` (``STARTED``/``ACTIVE``/``RECOVERED``),
``score_at_start`` / ``score_min`` / ``score_at_recovery`` / ``score_delta``
— built by :func:`build_grouped_episode`, which reuses the existing
sample-derived derivation (peak/baseline/duration for the primary condition)
and replays contributor correlation across **all** episode metrics. Missing
values remain ``None`` (never fabricated as zero).

### UI

``gui/performance_page.py``'s existing "Performance episodes" cards now show
the episode id, escalated severity, affected metrics, score impact
(start → minimum, recovery, Δ) and lifecycle state. The GUI still renders
only ``orchestrator.view_state()`` — no second cache, no analysis, no new
worker or refresh loop.

### Safety boundaries (unchanged, non-negotiable)

Exactly one MonitorWorker/QTimer pipeline; no Qt/subprocess/device access in
``performance/``; contributors come only from the already-resolved
BackgroundAppsSnapshot; wording stays observational ("observed contributor",
"was repeatedly observed") — correlation is never stated as causation;
nothing destructive is triggered from analysis.

### Tests added (Phase 5b)

13 new deterministic device-free tests in
``tests/test_performance_episodes.py``: single-condition open; STARTED→ACTIVE
lifecycle; no duplicate episodes under sustained breach; overlapping
cpu+memory form ONE episode; partial recovery keeps the episode ACTIVE;
closure only after all members recover; non-overlapping incidents produce
distinct sequential ids (newest-first ordering); escalation retention
(warning→critical stays critical); contributor preservation on completed
episodes; score trajectory (start/min/recovery/delta, recovery observed);
steady-state ticks mutate nothing and respect evidence retention; retention
cap; missing values stay missing; plus disconnect/reconnect resets and the
forbidden-token architecture audit extended with ``pm list packages`` /
``BackgroundWorker``.

### Validation status (Phase 5b)

Full suite: **1916 passed**. ``ruff check src tests`` clean; ``mypy`` clean
for the enforced scope and ``performance/`` (21 source files). Version
remains **0.8.1** — no bump, tag, push or release.

### Timeline episode wiring (completed)

When an episode actually closes — and only then — the orchestrator appends
exactly **one** additional :class:`PerformanceEvent` to its existing event
stream: ``"Performance episode P-NNN recovered"``, typed
``PerformanceEventType.EPISODE_RECOVERY`` (mapped to the shared metric-alert
timeline type by the unchanged adapter table), carrying the escalated episode
severity, a purely observational description (conditions, affected metrics,
duration) and the deterministic episode id as identity vocabulary
(``evidence_ids``). No events are emitted while an episode is open; ids
restart after session reset. The announcement flows through the existing
``events_ready`` → ``_on_performance_events`` → ``to_timeline_event`` path,
so incidents now appear as closed entries on the unified Timeline without any
new pipeline, polling or GUI code. Locked by
``tests/test_performance_episode_timeline.py`` (5 tests).
