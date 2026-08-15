"""Process inspection detail panel: renders a ProcessInspectionSnapshot.

This is a read-only presentation view. It consumes an already-normalized
snapshot (or an explicit "process gone" state) and renders labels; it never
sends commands, never reads device output and never computes raw deltas.

Memory labels are precise: "Resident" means VmRSS, "Virtual" means VmSize and
"Shared" means RssShmem. RSS is not PSS and is not "total RAM the app owns";
pages shared with other processes are counted for every owner.

Device Actions live here: Open App / App Info / Force Stop. A button is
usable only when the selected process resolves to a verified installed
package (see ``action.resolution``); kernel and system processes all render
"Actions unavailable" and cannot receive application actions.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...action import ActionErrorKind, ActionResult, resolve_package
from ...network_investigation.models import NetworkInvestigationSnapshot
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

#: Caption shown when the device denied the socket-table reads.
_NETWORK_SOURCE_UNAVAILABLE = (
    "Network attribution unavailable: Android blocks these socket reads without root."
)
#: Caption shown when the tables were read but held no sockets at all.
_NETWORK_NO_CONNECTIONS = "No connections were observed on the device."
#: Caption shown while no investigation sample has arrived yet.
_NETWORK_AWAITING = "Awaiting the first network investigation sample…"

_NETWORK_COLUMNS = ("Protocol", "Local", "Remote", "State")


def _fmt_mem(kib: int | None) -> str:
    return "N/A" if kib is None else format_kib(kib)


def _endpoint(address: str, port: int | None) -> str:
    """Format ``address:port`` without ever inventing a value."""
    if address is None or port is None:
        return "N/A"
    return f"{address}:{port}"


def _fmt_io(value: int | None) -> str:
    """Format an I/O byte counter; ``None`` stays "Unavailable" (never 0)."""
    return "Unavailable" if value is None else f"{value:,} B"


#: Explanation for I/O counters Android does not expose to this process.
_IO_UNAVAILABLE_TOOLTIP = "Unavailable due to Android process permissions."


class ProcessInspectorWidget(QWidget):
    """Detail view shown when a process row is selected."""

    #: User pressed the hide button.
    closed = Signal()

    #: (action, package) the user clicked an action button. Only emitted
    #: when the selected process resolved to a verified package identity.
    action_requested = Signal(str, str)

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
            value.setProperty("mono", True)
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

        # ------------------------------------------------------------------
        # Device Actions row
        # ------------------------------------------------------------------
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._actions_caption = QLabel("Actions")
        self._actions_caption.setObjectName("caption")
        action_row.addWidget(self._actions_caption)
        self._open_btn = self._make_action_button("Open App")
        self._info_btn = self._make_action_button("App Info")
        self._stop_btn = self._make_action_button("Force Stop", primary=False)
        action_row.addWidget(self._open_btn)
        action_row.addWidget(self._info_btn)
        action_row.addWidget(self._stop_btn)
        self._open_btn.clicked.connect(lambda: self._on_action_clicked("open_app"))
        self._info_btn.clicked.connect(lambda: self._on_action_clicked("app_info"))
        self._stop_btn.clicked.connect(lambda: self._on_action_clicked("force_stop"))
        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        action_row.addWidget(self._status, 1)
        layout.addLayout(action_row)

        # ------------------------------------------------------------------
        # Network connections section (M14, UID-level attribution only)
        # ------------------------------------------------------------------
        self._network_caption = QLabel(_NETWORK_AWAITING)
        self._network_caption.setObjectName("caption")
        self._network_caption.setWordWrap(True)
        layout.addWidget(self._network_caption)

        self._network_table = QTableWidget(0, len(_NETWORK_COLUMNS))
        self._network_table.setHorizontalHeaderLabels(list(_NETWORK_COLUMNS))
        self._network_table.verticalHeader().setVisible(False)
        self._network_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._network_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._network_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self._network_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._network_table.setMaximumHeight(180)
        layout.addWidget(self._network_table)

        self._network_data: NetworkInvestigationSnapshot | None = None

        self._packages: set[str] = set()
        self._last_snapshot: ProcessInspectionSnapshot | None = None
        self._resolved_package: str | None = None
        self._busy = False

        self.hide()

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------

    def _make_action_button(self, text: str, primary: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primary" if primary else "secondary")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setEnabled(False)
        return button

    def set_snapshot(
        self,
        snapshot: ProcessInspectionSnapshot,
        network_data: NetworkInvestigationSnapshot | None = None,
    ) -> None:
        """Populate the panel with a normalized inspection result and show it.

        Selection state is reset FIRST: the previous process's verified
        package, action buttons and result status must never leak into the
        new selection. Buttons are then recomputed from the new identity.
        """
        self._network_data = network_data
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
            "I/O Read": _fmt_io(snapshot.io_read_bytes),
            "I/O Write": _fmt_io(snapshot.io_write_bytes),
        }
        for field, text in values.items():
            self._rows[field].setText(text)

        self._rows["I/O Read"].setToolTip(
            _IO_UNAVAILABLE_TOOLTIP if snapshot.io_read_bytes is None else ""
        )
        self._rows["I/O Write"].setToolTip(
            _IO_UNAVAILABLE_TOOLTIP if snapshot.io_write_bytes is None else ""
        )

        if snapshot.command_line:
            self._command_line.setText(f"Command Line\n{snapshot.command_line}")
            self._command_line.show()
        else:
            self._command_line.hide()

        self._last_snapshot = snapshot
        self._resolved_package = None
        self._status.setText("")
        self._status.setObjectName("muted")
        self._render_network()
        self._refresh_actions()
        self.show()

    def set_network_data(self, network_data: NetworkInvestigationSnapshot) -> None:
        """Refresh the network section when a new investigation sample arrives.

        Only re-renders when a process panel is currently displayed; the
        panel shows nothing (and re-renders on its next open) otherwise.
        """
        self._network_data = network_data
        if self._last_snapshot is not None:
            self._render_network()

    def _render_network(self) -> None:
        """Render the network section for the currently shown snapshot.

        Four distinct states are presented honestly: awaiting the first
        investigation sample, the device refusing the socket reads, the
        tables being read with no sockets in them at all, and the process
        having no sockets attributed to its UID. Nothing is ever fabricated.
        """
        snapshot = self._last_snapshot
        board = self._network_data

        if snapshot is None or snapshot.uid is None:
            self._network_caption.setText(
                _NETWORK_SOURCE_UNAVAILABLE
                if snapshot is not None
                else _NETWORK_AWAITING
            )
            self._network_table.setRowCount(0)
            return

        if board is None:
            self._network_caption.setText(_NETWORK_AWAITING)
            self._network_table.setRowCount(0)
            return

        if not board.source_available:
            self._network_caption.setText(_NETWORK_SOURCE_UNAVAILABLE)
            self._network_table.setRowCount(0)
            return

        sockets = board.sockets_for_uid(snapshot.uid)
        if not board.sockets:
            self._network_caption.setText(_NETWORK_NO_CONNECTIONS)
        elif not sockets:
            self._network_caption.setText(
                f"No connections attributed to this process (UID {snapshot.uid})."
            )
        else:
            packages = board.packages_for_uid(snapshot.uid)
            package_text = ", ".join(packages) if packages else "unknown package"
            self._network_caption.setText(
                f"Connections attributed to UID {snapshot.uid} ({package_text})"
            )

        self._network_table.setRowCount(len(sockets))
        for row_index, socket in enumerate(sockets):
            protocol = socket.protocol.upper()
            values = (
                f"{protocol} {socket.family.upper()}",
                (
                    _endpoint(socket.local_address, socket.local_port)
                    if socket.local_address is not None
                    else "N/A"
                ),
                (
                    _endpoint(socket.remote_address, socket.remote_port)
                    if socket.remote_address is not None
                    else "N/A"
                ),
                socket.state or "-",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                self._network_table.setItem(row_index, column, item)

    def set_gone(self, pid: int, message: str | None = None) -> None:
        """Show the clean "process no longer exists" state."""
        self._title.setText("Process no longer available.")
        detail = f"PID {pid} exited before inspection completed."
        if message:
            detail = f"{detail} ({message})"
        self._subtitle.setText(detail)
        for value in self._rows.values():
            value.setText("N/A")
            value.setToolTip("")
        self._command_line.hide()
        self._network_caption.setText(_NETWORK_AWAITING)
        self._network_table.setRowCount(0)
        self._last_snapshot = None
        self._resolved_package = None
        self._status.setText("")
        self._actions_caption.setText("Actions unavailable")
        self._set_buttons(False)
        self.show()

    # ------------------------------------------------------------------
    # Device Actions
    # ------------------------------------------------------------------

    def set_packages(self, packages: set[str]) -> None:
        """Provide the verified installed-package set for identity checks."""
        self._packages = set(packages)
        self._refresh_actions()

    def set_actions_busy(self, busy: bool) -> None:
        """Disable action buttons while an action is in flight."""
        self._busy = busy
        self._refresh_actions()

    def show_action_result(self, result: ActionResult) -> None:
        """Render the typed outcome of an action, if it still belongs here.

        The result is rendered only when its package still matches the
        *currently selected* process's verified package. If the selection
        changed while the action was in flight, the outcome belongs to the
        previous process and is discarded — a stale "Opened X" message must
        never appear under a different process. The busy lock is released
        either way so buttons follow the current selection.
        """
        self._busy = False
        if result.package_name != self._resolved_package:
            self._refresh_actions()
            return
        self._refresh_actions()
        self._status.setText(result.message)
        if result.success or result.error_kind is None:
            self._status.setObjectName("muted")
        else:
            self._status.setObjectName("statusWarn")
        app = QApplication.instance()
        if app is not None:
            app.style().unpolish(self._status)
            app.style().polish(self._status)
        self._status.update()

    def display_name(self) -> str:
        """Best human-readable name for the currently shown process."""
        if self._last_snapshot is not None:
            return self._last_snapshot.name or ""
        return ""

    def resolved_package(self) -> str | None:
        """The verified package identity of the shown process (or None)."""
        return self._resolved_package

    def _refresh_actions(self) -> None:
        """Atomic button/caption update derived ONLY from the current identity.

        All three buttons always share one enabled state coming from a
        freshly recomputed verified package for the *current* snapshot —
        never from a previously selected process. The safe default when no
        identity can be verified is all buttons disabled.
        """
        snapshot = self._last_snapshot
        if snapshot is not None:
            self._resolved_package = resolve_package(
                snapshot.name,
                snapshot.command_line,
                self._packages,
            )
        else:
            self._resolved_package = None

        if snapshot is None:
            self._actions_caption.setText("Actions unavailable")
            self._set_buttons(False)
            return

        package = self._resolved_package
        if package is not None:
            self._actions_caption.setText(f"Actions for {package}")
        else:
            self._actions_caption.setText("Application actions unavailable for this process.")

        if self._busy:
            self._set_buttons(False)
            return

        self._set_buttons(package is not None)

    def _set_buttons(self, enabled: bool) -> None:
        self._open_btn.setEnabled(enabled)
        self._info_btn.setEnabled(enabled)
        self._stop_btn.setEnabled(enabled)

    def _on_action_clicked(self, action: str) -> None:
        package = self._resolved_package
        if package is None:
            return
        self.action_requested.emit(action, package)