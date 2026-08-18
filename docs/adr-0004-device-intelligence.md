# ADR-0004 — Device Intelligence: deterministic health, rules, recommendations and controlled automation

Status: Accepted
Date: 2026-08-19

## Context

v0.6 and v0.7 turned Android Task Manager from a monitor into a
*diagnoser* and *manager*: normalized snapshots, diagnostics rules, and a
safe application-action layer with strict identity discipline. v0.8 adds
the missing layer: turning the monitoring data the app already collects
into *structure* (history, health, timeline) and *action* (rules,
recommendations, automation) — without ever weakening the v0.7 safety
protections.

The constraints that shape this design:

* the project is read-only by construction; only six explicit,
  package-verified device actions may ever change device state;
* every ADB call must stay on worker threads, and the GUI must not add
  polling of its own;
* the device's output (process names, serials, package names) is
  untrusted input;
* a value that cannot be read must be reported honestly — never guessed,
  never fabricated into a finding;
* everything must remain deterministic and testable without a device.

## Decision

1. **A pure, GUI-independent intelligence core.** New packages
   `history/`, `health/`, `timeline/`, `rules/`, `recommend/` and
   `automation/` are pure functions of typed snapshot models and explicit
   monotonic clocks. The GUI owns the state and the worker wiring; the
   engines own the decisions. No AI, no model, no cloud — the core is
   deterministic by construction.

2. **No new polling.** The Intelligence page is populated exclusively by
   the monitor's existing snapshot signals (`snapshots`, `storage_snapshot`,
   `serial_ready`, `connection_changed`, the apps inventory). History is
   recorded from the snapshots that already flow; rules/health/
   recommendations evaluate on the same events. The page has no timers.

3. **Bounded, session-scoped state.** Metric history windows are bounded
   per metric (CPU 180 / memory 120 / battery 96 / storage 60 samples) and
   deduplicate consecutive identical values; the timeline is bounded (256
   events); automation tasks and cooldown/budget state reset on every
   `begin_session` (reconnect never inherits the previous device's data —
   history, timeline, rules and automation all restart fresh).

4. **Health is honest about evidence.** `evaluate_device_health` scores
   only readable components; unavailable components contribute neither
   score nor finding. An all-unavailable device reports an honest
   "unavailable" status, never a plausible failure. Thresholds come
   exclusively from the canonical `thresholds.py` module.

5. **Identity link to the v0.7 inventory (process → app).** A heavy-user-
   process recommendation is proposed only when the process name is a
   *verified installed package* (the v0.7 resolver/inventory) **and** a
   *user-category package*. Spoofed process names can never become
   force-stop targets, and system/protected applications never receive
   destructive proposals — matching the v0.7 capability gate.

6. **Automation is approval-gated and never destructive.** The automation
   engine submits (validates target, fails closed), requires an explicit
   approval (the user's Apply click), then gates on cooldown (default
   300 s per (action, target)), a per-session execution budget (default 3
   per target — loop protection) and executor availability. Destructive
   actions are excluded from automation by construction, *even when
   explicitly approved*; the executor is the same v0.7 action worker, so
   an automated action carries the exact safety guarantees of a manual
   one.

7. **System-app protection in the recommendation layer.** The GUI passes
   the inventory's authoritative category classification into the
   recommendation engine as the *targetable* set — the same
   SYSTEM/USER boundary the v0.7 UI enforces for its destructive buttons.

8. **GUI integration is presentation-only.** `IntelligencePage` renders
   engine outputs and forwards two signals (apply, navigate); MainWindow
   owns the engines, the session lifecycle and the worker wiring. Finding
   navigation re-verifies identity at the window and runs the detail read
   on the existing apps worker.

## Consequences

* Health/rules/recommendations/automation are fully unit-testable with
  fixtures (no device required), and the GUI flows are covered by the
  headless Qt suite.
* Reconnect behavior is strict: a fresh device session starts from a
  clean slate (history, timeline, cooldowns, budgets, task list).
* Automation is deliberately narrow: it can only run what the v0.7 action
  layer can safely run, never a destructive action, and never without the
  user's explicit click — this is a documented safety limitation, not a
  feature gap.
* The Intelligence page never creates ADB traffic of its own; its cost is
  the pure evaluation over snapshots the monitor already collected.

## Related documents

* ADR-0001 (incident reporting), ADR-0002 (investigation core),
  ADR-0003 (device management) — the v0.6/v0.7 safety heritage this
  design builds on.
* `docs/m14-network-research.md` — the Android capability research behind
  the attribution limitations the intelligence layer inherits.