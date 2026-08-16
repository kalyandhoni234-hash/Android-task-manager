"""Process tree dialog: read-only parent/child hierarchy of one snapshot.

Shows the pure ``build_process_tree`` result: roots, children ordered by
PID, and an honest note listing PIDs whose parent is not in the snapshot
(never inferred). For each node the UID's installed packages (from the
latest network investigation) are shown when available — that is the
existing UID-level attribution, never a PID-level claim.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..investigation.models import ProcessNode, ProcessTree
from ..network_investigation.models import NetworkInvestigationSnapshot


class ProcessTreeDialog(QDialog):
    """Parent/child view of the latest process snapshot."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Process Tree")
        self.resize(780, 560)

        self._title = QLabel("")
        self._title.setObjectName("incidentDialogTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)

        self._note = QLabel("")
        self._note.setObjectName("statusWarn")
        self._note.setTextFormat(Qt.TextFormat.PlainText)
        self._note.setWordWrap(True)
        self._note.hide()

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Process", "PID", "PPID", "UID", "Category"])
        self._tree.setColumnWidth(0, 320)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._note)
        layout.addWidget(self._tree, 1)
        layout.addLayout(buttons)

        close_btn.clicked.connect(self.accept)

    # ------------------------------------------------------------------
    # State entry points (MainWindow calls these on the GUI thread)
    # ------------------------------------------------------------------

    def show_tree(
        self,
        tree: ProcessTree,
        network_investigation: NetworkInvestigationSnapshot | None = None,
    ) -> None:
        """Render the process hierarchy with UID-level package notes."""
        self._title.setText(
            f"Process hierarchy — {len(tree.nodes)} process(es), "
            f"{len(tree.roots)} root(s)"
        )
        if tree.unresolved_parents:
            self._note.setText(
                "The following process(es) have a parent PID that is not in "
                "this snapshot — the parent is reported as unavailable, never "
                "inferred: "
                + ", ".join(str(pid) for pid in tree.unresolved_parents)
            )
            self._note.show()
        else:
            self._note.hide()

        self._tree.clear()
        for root in tree.roots:
            self._tree.addTopLevelItem(
                self._build_item(root, network_investigation)
            )

    def _build_item(
        self,
        node: ProcessNode,
        network_investigation: NetworkInvestigationSnapshot | None,
    ) -> QTreeWidgetItem:
        packages = ""
        if network_investigation is not None and node.uid is not None:
            names = network_investigation.uid_packages.get(node.uid, ())
            if names:
                packages = "  (" + ", ".join(sorted(names)) + ")"
        item = QTreeWidgetItem(
            [
                f"{node.name}{packages}",
                str(node.pid),
                str(node.ppid) if node.ppid is not None else "—",
                str(node.uid) if node.uid is not None else "—",
                str(node.category.value),
            ]
        )
        for child in node.children:
            item.addChild(self._build_item(child, network_investigation))
        return item