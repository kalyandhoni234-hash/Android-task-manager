"""Headless GUI tests for the Investigation features.

Offscreen Qt platform; never touches a device. Covers the BaselinePanel
investigation button laws, the timeline / why-flagged / process-tree
dialogs, and the MainWindow handlers that feed them from collected data.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.gui.investigation_dialog import InvestigationDialog
from android_task_manager.gui.main_window import MainWindow
from android_task_manager.gui.process_tree_dialog import ProcessTreeDialog
from android_task_manager.gui.why_flagged_dialog import WhyFlaggedDialog
from android_task_manager.gui.widgets.baseline_panel import BaselinePanel
from tests import investigation_fixtures as fx


@pytest.fixture(scope="module")
def qtapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Panel button laws
# ---------------------------------------------------------------------------


def test_panel_investigation_buttons_follow_drift_state(qtapp) -> None:
    panel = BaselinePanel()
    assert not panel._timeline_btn.isEnabled()
    assert not panel._tree_btn.isEnabled()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    panel.set_baseline(baseline)
    assert not panel._timeline_btn.isEnabled()
    assert not panel._tree_btn.isEnabled()
    drift = fx.drift_report(
        baseline,
        fx.snapshot(fx.ts("2026-01-01T10:00:05Z"), processes=(fx.STABLE_A, fx.STABLE_APP)),
        (),
    )
    panel.show_drift(drift, fx.heuristic_report((), (), fx.ts("2026-01-01T10:00:05Z")))
    assert panel._timeline_btn.isEnabled()
    assert panel._tree_btn.isEnabled()
    panel.close()


def test_panel_investigation_buttons_reset_with_baseline(qtapp) -> None:
    panel = BaselinePanel()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    panel.set_baseline(baseline)
    drift = fx.drift_report(
        baseline,
        fx.snapshot(fx.ts("2026-01-01T10:00:05Z"), processes=(fx.STABLE_A, fx.STABLE_APP)),
        (),
    )
    panel.show_drift(drift, fx.heuristic_report((), (), fx.ts("2026-01-01T10:00:05Z")))
    assert panel._timeline_btn.isEnabled()
    panel.set_baseline(None)
    assert not panel._timeline_btn.isEnabled()
    assert not panel._tree_btn.isEnabled()
    panel.close()


def test_panel_investigation_clicks_emit_signals(qtapp) -> None:
    panel = BaselinePanel()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    panel.set_baseline(baseline)
    drift = fx.drift_report(
        baseline,
        fx.snapshot(fx.ts("2026-01-01T10:00:05Z"), processes=(fx.STABLE_A, fx.STABLE_APP)),
        (),
    )
    panel.show_drift(drift, fx.heuristic_report((), (), fx.ts("2026-01-01T10:00:05Z")))
    timeline_clicked, tree_clicked = [], []
    panel.timeline_requested.connect(lambda: timeline_clicked.append(True))
    panel.process_tree_requested.connect(lambda: tree_clicked.append(True))
    panel._timeline_btn.click()
    panel._tree_btn.click()
    assert timeline_clicked and tree_clicked
    panel.close()


def test_panel_why_button_emits_signal(qtapp) -> None:
    panel = BaselinePanel()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    panel.set_baseline(baseline)
    drift = fx.drift_report(
        baseline,
        fx.snapshot(fx.ts("2026-01-01T10:00:05Z"), processes=(fx.STABLE_A, fx.STABLE_APP)),
        (),
    )
    signal = fx.signal("RULE_TEST", "MEDIUM", "com.example.app")
    panel.show_drift(drift, fx.heuristic_report(("RULE_TEST",), (signal,), fx.ts("2026-01-01T10:00:05Z")))
    why = []
    panel.why_requested.connect(lambda s: why.append(s))
    # The per-signal Why? button lives in the signal row.
    why_buttons = [
        b for b in panel.findChildren(type(panel._save_btn))
        if b.text() == "Why?"
    ]
    assert why_buttons
    why_buttons[0].click()
    assert why and why[0] is signal
    panel.close()


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


def test_timeline_dialog_renders_events_deterministically(qtapp) -> None:
    dialog = InvestigationDialog()
    events = fx.timeline_events()
    dialog.show_timeline(events)
    assert dialog._list.count() == len(events)
    assert dialog._title.text().startswith("Investigation timeline")
    # First event selected → details rendered.
    details = dialog._detail.toPlainText()
    assert events[0].event_id in details
    assert events[0].event_type in details
    dialog.close()


def test_timeline_dialog_empty_state(qtapp) -> None:
    dialog = InvestigationDialog()
    dialog.show_timeline(())
    assert dialog._list.count() == 0
    assert "0 event(s)" in dialog._title.text()
    dialog.close()


def test_why_flagged_dialog_renders_facts_and_honesty_line(qtapp) -> None:
    dialog = WhyFlaggedDialog()
    signal = fx.signal("NEW_PROCESS_WITH_ACTIVE_SOCKET", "MEDIUM", "com.example.app")
    explanation = fx.explanation(
        headline="The facts behind this signal.",
        facts=fx.facts(),
    )
    dialog.show_explanation(signal, explanation)
    text = dialog._view.toPlainText()
    assert "NEW_PROCESS_WITH_ACTIVE_SOCKET" in text
    assert "MEDIUM" in text
    assert "EVIDENCE" in text
    assert "does not determine whether the entity is malicious" in text
    dialog.close()


def test_why_flagged_dialog_empty_facts_state(qtapp) -> None:
    dialog = WhyFlaggedDialog()
    dialog.show_explanation(
        fx.signal("RULE", "MEDIUM", "x"),
        fx.explanation(headline="h", facts=()),
    )
    assert "No evidence facts could be derived" in dialog._view.toPlainText()
    dialog.close()


def test_why_flagged_dialog_error_state(qtapp) -> None:
    dialog = WhyFlaggedDialog()
    dialog.show_error("Could not explain this signal from the collected data.")
    assert "Could not explain" in dialog._view.toPlainText()
    dialog.close()


def test_process_tree_dialog_renders_hierarchy_and_unresolved_note(qtapp) -> None:
    dialog = ProcessTreeDialog()
    snapshot = fx.tree_snapshot()
    from android_task_manager.investigation.tree import build_process_tree

    tree = build_process_tree(snapshot)
    dialog.show_tree(tree, fx.network_snapshot(1.0, (), uid_packages={}))
    assert "Process hierarchy" in dialog._title.text()
    assert not dialog._note.isHidden()
    assert "never inferred" in dialog._note.text()
    assert dialog._tree.topLevelItemCount() == len(tree.roots)
    dialog.close()


def test_process_tree_dialog_hides_note_when_clean(qtapp) -> None:
    dialog = ProcessTreeDialog()
    snapshot = fx.process_snapshot(
        1.0,
        (
            fx.process_info(1, "init", 0, ppid=None),
            fx.process_info(754, "system_server", 1000, ppid=1),
        ),
    )
    from android_task_manager.investigation.tree import build_process_tree

    dialog.show_tree(build_process_tree(snapshot))
    assert dialog._note.isHidden()
    assert dialog._tree.topLevelItemCount() == 1
    dialog.close()


# ---------------------------------------------------------------------------
# MainWindow wiring
# ---------------------------------------------------------------------------


def test_main_window_timeline_handler_opens_dialog(qtapp) -> None:
    window = MainWindow()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    window._baseline = baseline
    window._current_snapshot = current
    window._drift_report = fx.drift_report(baseline, current, ())
    window._on_timeline_requested()
    assert window._investigation_dialog is not None
    assert window._investigation_dialog._list.count() > 0
    window.close()


def test_main_window_tree_handler_opens_dialog(qtapp) -> None:
    window = MainWindow()
    window._latest_processes = fx.tree_snapshot()
    window._on_process_tree_requested()
    assert window._process_tree_dialog is not None
    assert window._process_tree_dialog._tree.topLevelItemCount() > 0
    window.close()


def test_main_window_tree_handler_without_processes_is_noop(qtapp) -> None:
    window = MainWindow()
    window._latest_processes = None
    window._on_process_tree_requested()
    assert window._process_tree_dialog is None
    window.close()


def test_main_window_why_handler_shows_facts_or_honest_error(qtapp) -> None:
    window = MainWindow()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP, fx.process(10200, "com.example.app", None)),
        sockets=(fx.socket("tcp", "0.0.0.0", 4444, uid=10200),),
    )
    drift = fx.drift_report(
        baseline,
        current,
        (
            fx.drift_event("process", "NEW", "com.example.app"),
            fx.drift_event("socket", "NEW", "tcp:0.0.0.0:4444"),
        ),
    )
    window._baseline = baseline
    window._current_snapshot = current
    window._drift_report = drift
    window._latest_processes = fx.process_snapshot(
        1.0, (fx.process_info(18472, "com.example.app", 10200, ppid=754),)
    )
    window._latest_network_investigation = fx.network_snapshot(
        1.0,
        (fx.socket_info("tcp", "0.0.0.0", 4444, state="LISTEN", uid=10200, pid=18472),),
        uid_packages={10200: ("com.example.app",)},
    )
    signal = fx.signal(
        "NEW_PROCESS_WITH_ACTIVE_SOCKET", "MEDIUM", "com.example.app",
        contributing_events=("com.example.app", "tcp:0.0.0.0:4444"),
    )
    window._why_dialog = WhyFlaggedDialog()
    window._on_why_requested(signal)
    text = window._why_dialog._view.toPlainText()
    assert "EVIDENCE" in text
    assert "facts only" in text
    window.close()


def test_main_window_why_handler_degrades_honestly(qtapp) -> None:
    """Unknown entity: only the signal's own facts exist, no data facts."""
    window = MainWindow()
    baseline = fx.snapshot(
        fx.ts("2026-01-01T10:00:00Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    current = fx.snapshot(
        fx.ts("2026-01-01T10:00:05Z"),
        processes=(fx.STABLE_A, fx.STABLE_APP),
    )
    window._baseline = baseline
    window._current_snapshot = current
    window._drift_report = fx.drift_report(baseline, current, ())
    window._why_dialog = WhyFlaggedDialog()
    signal = fx.signal("RULE", "MEDIUM", "unknown.entity")
    window._on_why_requested(signal)
    text = window._why_dialog._view.toPlainText()
    assert "unknown.entity" in text
    assert "category: signal" in text
    assert "category: process" not in text
    assert "facts only" in text
    window.close()