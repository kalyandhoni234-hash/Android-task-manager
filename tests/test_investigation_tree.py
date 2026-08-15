"""Process tree (parent/child) tests.

No device required. Verifies the hierarchy is built from collected
PPIDs only, missing parents are reported as unresolved (never inferred),
children are ordered by PID, and the ASCII renderer is deterministic.
"""

from __future__ import annotations

from android_task_manager.investigation.tree import (
    build_process_tree,
    format_tree,
)
from tests import investigation_fixtures as fx


def _tree():
    return build_process_tree(fx.tree_snapshot())


def test_hierarchy_built_from_ppids() -> None:
    tree = _tree()
    by_pid = {node.pid: node for node in tree.nodes}
    assert by_pid[18472].ppid == 754
    assert by_pid[18491].ppid == 18472
    assert by_pid[18493].ppid == 18472


def test_roots_are_pidless_and_unresolved() -> None:
    tree = _tree()
    root_pids = sorted(root.pid for root in tree.roots)
    # init (ppid 0, not in snapshot) and kthreadd (ppid 0) are roots;
    # orphan.process (ppid 99999, not in snapshot) is a root too.
    assert root_pids == [1, 2, 90001]


def test_unresolved_parents_listed_honestly() -> None:
    tree = _tree()
    # init/kthreadd name pid 0 (the kernel pseudo-parent, never listed by
    # ps) and orphan.process names 99999 — none of them in the snapshot.
    assert tree.unresolved_parents == (1, 2, 90001)


def test_children_ordered_by_pid() -> None:
    tree = _tree()

    def find(node, pid):
        if node.pid == pid:
            return node
        for child in node.children:
            found = find(child, pid)
            if found is not None:
                return found
        return None

    app = find(tree.roots[0], 18472)
    assert app is not None
    assert [child.pid for child in app.children] == [18491, 18493]


def test_no_ancestry_inference() -> None:
    snapshot = fx.process_snapshot(
        1.0,
        (fx.process_info(10, "a", 0, ppid=None),),
    )
    tree = build_process_tree(snapshot)
    assert tree.roots[0].ppid is None
    assert tree.unresolved_parents == ()


def test_format_tree_deterministic() -> None:
    first = format_tree(_tree())
    second = format_tree(_tree())
    assert first == second
    assert "system_server (pid 754)" in first
    assert "com.example.app (pid 18472)" in first


def test_format_tree_max_depth_summarizes() -> None:
    outline = format_tree(_tree(), max_depth=2)
    assert "com.example.app (pid 18472)" in outline
    assert "child process(es)" in outline
    assert "com.example.app:renderer" not in outline


def test_empty_snapshot_yields_empty_tree() -> None:
    tree = build_process_tree(fx.process_snapshot(1.0, ()))
    assert tree.roots == ()
    assert tree.nodes == ()
    assert tree.unresolved_parents == ()