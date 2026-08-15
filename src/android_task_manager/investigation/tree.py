"""Read-only process hierarchy (parent/child analysis).

Builds a derived tree view over one :class:`ProcessSnapshot` using the
collector's PID / PPID / name / UID / classification rows. It never
infers ancestry:

* a node whose parent PID is not in the snapshot becomes a **root** with
  its parent reported as unavailable (``ppid`` stays as collected; the
  tree does not fabricate a parent);
* PID reuse is the baseline layer's identity concern — within one
  snapshot every PID is unique (the parser keeps the first occurrence),
  so the tree is built per snapshot and never merges PIDs across time.

Process ancestry is *evidence*, never a verdict: the tree structure is a
fact of the snapshot, and security interpretation stays in the
investigation layer (an unexpected process + unexpected parent + new
network connection means "review required", not "malicious").
"""

from __future__ import annotations

from ..process.models import ProcessCategory, ProcessSnapshot
from .models import ProcessNode, ProcessTree


def build_process_tree(snapshot: ProcessSnapshot) -> ProcessTree:
    """Build the parent/child hierarchy of *snapshot*.

    Deterministic: roots and children are ordered by PID. Nodes whose
    parent is missing or unknown become roots; their PIDs are listed in
    ``unresolved_parents`` when a non-``None`` PPID points outside the
    snapshot.
    """
    by_pid: dict[int, ProcessNode] = {}
    for info in snapshot.processes:
        by_pid[info.pid] = ProcessNode(
            pid=info.pid,
            name=info.name,
            uid=info.uid,
            ppid=info.ppid,
            category=info.category,
        )

    unresolved: list[int] = []
    children_of: dict[int, list[int]] = {}
    for pid, node in by_pid.items():
        if node.ppid is None:
            continue
        if node.ppid in by_pid:
            children_of.setdefault(node.ppid, []).append(pid)
        else:
            unresolved.append(pid)

    roots: list[int] = []
    for pid, node in by_pid.items():
        if node.ppid is None or node.ppid not in by_pid:
            roots.append(pid)

    def build(pid: int) -> ProcessNode:
        node = by_pid[pid]
        children = tuple(
            build(child) for child in sorted(children_of.get(pid, ()))
        )
        return ProcessNode(
            pid=node.pid,
            name=node.name,
            uid=node.uid,
            ppid=node.ppid,
            category=node.category,
            children=children,
        )

    nodes = tuple(sorted(by_pid.values(), key=lambda n: n.pid))
    roots_nodes = tuple(build(pid) for pid in sorted(roots))
    return ProcessTree(
        timestamp=snapshot.timestamp,
        nodes=nodes,
        roots=roots_nodes,
        unresolved_parents=tuple(sorted(unresolved)),
    )


def format_tree(tree: ProcessTree, *, max_depth: int | None = None) -> str:
    """Render the tree as a deterministic ASCII outline (for tests/CLI).

    ``max_depth`` bounds the depth (children below it are summarized);
    ``None`` renders everything.
    """
    lines: list[str] = []

    def walk(node: ProcessNode, bar_prefix: str, connector: str, depth: int) -> None:
        lines.append(f"{bar_prefix}{connector}{node.name} (pid {node.pid})")
        if max_depth is not None and depth >= max_depth:
            if node.children:
                lines.append(
                    f"{bar_prefix}{connector}… {len(node.children)} child process(es)"
                )
            return
        children = node.children
        for index, child in enumerate(children):
            last = index == len(children) - 1
            if connector == "":
                child_bar = bar_prefix
            else:
                child_bar = bar_prefix + ("    " if last else "│   ")
            walk(child, child_bar, "└── " if last else "├── ", depth + 1)

    for node in tree.roots:
        walk(node, "", "", 0)
    return "\n".join(lines)


__all__ = [
    "build_process_tree",
    "format_tree",
]