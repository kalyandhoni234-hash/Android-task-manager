"""Process inspection detail panel: renders a ProcessInspectionSnapshot.

This is a read-only presentation view. It consumes an already-normalized
snapshot (or an explicit "process gone" state) and renders labels; it never
sends commands, never reads device output and never computes raw deltas.

Memory labels are precise: "Resident" means VmRSS, "Virtual" means VmSize and
"Shared" means RssShmem. RSS is not PSS and is not "total RAM the app owns";
pages shared with other processes are counted for every owner.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...process.inspector_models import ProcessInspectionSnapshot
from ...terminal.renderer import format_kib
from . import panel_host

_FIELDS = (
    "CPU",
    "Memory",
    "State",
    "Threads",
    "Priority",
    "Nice",
    "Virtual",
    "Resident",
    "Shared",
    "I/O Read",
    "I/O Write",
)


def _fmt_mem(kib: int | None) -> str:
    return "N/A" if kib is None else format_kib(kib)


class ProcessInspectorWidget(QWidget):
    """Detail view shown when a process row is selected."""

    #: User pressed the hide button.
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "PROCESS INSPECTOR")

        title_row = QHBoxLayout()
        self._title = QLabel("")
        self._title.setObjectName("value")
        title_row.addWidget(self._title, 1)
        self._hide = QPushButton("Hide")
        self._hide.setObjectName("link")
        self._hide.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hide.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hide.clicked.connect(self.closed)
        title_row.addWidget(self._hide)
        layout.addLayout(title_row)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("muted")
        layout.addWidget(self._subtitle)

        self._rows: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        for index, field in enumerate(_FIELDS):
            label = QLabel(field)
            label.setObjectName("caption")
            value = QLabel("N/A")
            value.setObjectName("muted")
            grid.addWidget(label, index, 0)
            grid.addWidget(value, index, 1)
            self._rows[field] = value
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self._command_line = QLabel("")
        self._command_line.setObjectName("caption")
        self._command_line.setWordWrap(True)
        self._command_line.hide()
        layout.addWidget(self._command_line)

        self.hide()

    def set_snapshot(self, snapshot: ProcessInspectionSnapshot) -> None:
        """Populate the panel with a normalized inspection result and show it."""
        self._title.setText(snapshot.name or f"PID {snapshot.pid}")
        uid = "N/A" if snapshot.uid is None else str(snapshot.uid)
        self._subtitle.setText(f"PID {snapshot.pid}   UID {uid}")

        def pct(value: float | None) -> str:
            return "N/A" if value is None else f"{value:.1f}%"

        values = {
            "CPU": pct(snapshot.cpu_percent),
            "Memory": pct(snapshot.memory_percent),
            "State": snapshot.state or "N/A",
            "Threads": "N/A" if snapshot.threads is None else str(snapshot.threads),
            "Priority": "N/A" if snapshot.priority is None else str(snapshot.priority),
            "Nice": "N/A" if snapshot.nice is None else str(snapshot.nice),
            "Virtual": _fmt_mem(snapshot.virtual_memory_kb),
            "Resident": _fmt_mem(snapshot.resident_memory_kb),
            "Shared": _fmt_mem(snapshot.shared_memory_kb),
            "I/O Read": (
                "N/A" if snapshot.io_read_bytes is None else f"{snapshot.io_read_bytes:,} B"
            ),
            "I/O Write": (
                "N/A" if snapshot.io_write_bytes is None else f"{snapshot.io_write_bytes:,} B"
            ),
        }
        for field, text in values.items():
            self._rows[field].setText(text)

        if snapshot.command_line:
            self._command_line.setText(f"Command Line\n{snapshot.command_line}")
            self._command_line.show()
        else:
            self._command_line.hide()

        self.show()

    def set_gone(self, pid: int, message: str | None = None) -> None:
        """Show the clean "process no longer exists" state."""
        self._title.setText("Process no longer available.")
        detail = f"PID {pid} exited before inspection completed."
        if message:
            detail = f"{detail} ({message})"
        self._subtitle.setText(detail)
        for value in self._rows.values():
            value.setText("N/A")
        self._command_line.hide()
        self.show()