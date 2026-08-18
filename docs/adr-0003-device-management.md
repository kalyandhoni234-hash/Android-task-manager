# ADR-0003 — Device Management: safe application actions + applications manager

Status: Accepted
Date: 2026-08-18

## Context

v0.6.0 shipped three explicit device actions (Open App / App Info / Force
Stop) that are *read-oriented*: they inspect or stop, but they cannot change
the device's installed-application state. v0.7.0 turns the tool into a
device *manager*: an installed-application inventory (Applications page) and
per-package management actions (Enable / Disable / Uninstall). Management
actions are the first *mutating* commands the tool can send to the device,
so they need a safety model that matches the project's "read-only by
construction" heritage:

* destructive actions must be impossible to trigger accidentally (no
  one-click destructive control);
* system applications must never receive uninstall/disable requests —
  Android's `pm uninstall` on a system package typically fails anyway, and
  offering a guaranteed-failing destructive control is a UX lie;
* the identity discipline (package verification) from v0.6 must hold for
  every action, including the new ones;
* permission-denied outcomes must be detected from the device output, not
  guessed.

## Decision

1. **Typed outcome extension.** `ActionResult` gains an optional `target`
   and `details` field (trailing, defaulted — backwards compatible), and
   `ActionErrorKind` gains `NOT_SUPPORTED`, `PERMISSION_DENIED` and
   `INVALID_TARGET`. An unknown action is now a typed `INVALID_TARGET`
   failure (was the misleading `INVALID_PACKAGE`).
2. **Capability gate (`action/capability.py`).** `supported_actions(is_system,
   enabled)` is the single source of truth for which actions are *offered*:

   * system applications: LAUNCH / APP_INFO / FORCE_STOP only — never
     DISABLE / UNINSTALL;
   * enabled state unknown (`None`): no toggle at all (honest third value);
   * `DESTRUCTIVE_ACTIONS = (FORCE_STOP, DISABLE, UNINSTALL)` drives
     confirmation and busy-state handling.

   The gate is enforced twice: the widget renders buttons from it, and the
   window re-validates it before every dispatch (defense in depth — stale
   details can never smuggle a destructive request through).
3. **Explicit confirmations.** Force Stop / Disable / Uninstall always ask
   `QMessageBox.question` with the exact package named in the message; the
   default button is Cancel.
4. **New commands.** `enable` → `pm enable`, `disable` →
   `pm disable-user --user 0` (user-level: reversible, never `--user -1`),
   `uninstall` → `pm uninstall` (never `-k`, no cache preservation). All
   remain fixed argument lists through `ConnectionManager`.
5. **Permission-denied detection.** Device output is whitespace-normalized
   and matched against known Android denial phrases ("operation not
   allowed", "security exception", "permission denial", "not permitted");
   a match maps to the typed `PERMISSION_DENIED` state. "not installed"
   stays a not-found state, keeping the two honest failure modes apart.
6. **Applications inventory (`applications/` package).** One typed
   `ApplicationSnapshot` from `pm list packages -f -U --show-versioncode`
   merged with the `-s` / `-3` / `-d` sets — system/user/disabled are
   structural facts, never inferred. Per-package details come from
   `dumpsys package` on demand, including launchable-activity detection:
   the resolver-table header is matched by action **and** category intent so
   detection never depends on one header's wording.
7. **GUI.** A new APPLICATIONS sidebar page (table + details panel + action
   row + permission audit) driven by a dedicated `AppsWorker` (reads off the
   GUI thread, duplicate refreshes dropped, honest empty state on failure).
   The Process Inspector gains a **Manage** button that navigates to the
   page with the verified package selected (direct detail read when the
   inventory is stale). After a successful uninstall/disable/enable the
   inventory and the inspector's package set refresh automatically.

## Consequences

* The Applications page is the first management surface: it lists, inspects
  and acts — but every mutating path is gated (capability + confirmation)
  and typed (failure states render honestly, stale results are discarded by
  package matching).
* The action layer now has six actions; the safe default everywhere is
  "not offered" (all buttons disabled) until positive evidence exists.
* Monitoring and inspection remain strictly read-only; only the six
  explicit actions can touch the device, and three of them always ask first.
* `test_action_capability.py`, `test_action_service.py` (extended),
  `test_applications.py` and `test_apps_gui.py` lock the gate, the parsers
  and the GUI flows in; the full suite (1545 tests at this writing) runs
  headless with no physical device.