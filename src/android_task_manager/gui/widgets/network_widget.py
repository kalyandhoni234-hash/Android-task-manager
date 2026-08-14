"""Network widget: aggregate rates, active-interface list and a show-all toggle.

Presentation concerns handled here concern *display only*:

* **Active filtering.** By default only interfaces with nonzero current RX or
  TX throughput are shown, so a wall of ``0 B/s`` ccmni/dummy rows is hidden.
  The raw interfaces are never discarded from the ``NetworkSnapshot``.
* **Classification.** Interfaces are grouped under a display heuristic from
  ``gui.interface_classifier`` (Wi-Fi / Mobile Data / …). This label is a
  guess, not Android truth.
* **Sorting.** Within a group, interfaces are ordered by total throughput
  descending (never alphabetically).
* **Show all.** A compact toggle reveals idle/zero-throughput interfaces,
  including loopback and virtual ones, when the user wants to see everything.

The widget never sends commands, parses device output, or computes counter
deltas; it only reads the normalized ``NetworkSnapshot``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...network.models import NetworkSnapshot, NetworkThroughput
from ...terminal.renderer import format_throughput
from ..interface_classifier import CATEGORY_ORDER, classify_interface
from . import panel_host


def _is_active(throughput: NetworkThroughput | None) -> bool:
    """True if the interface currently moves traffic (rx or tx > 0)."""
    if throughput is None:
        return False
    return (throughput.rx_bytes_per_sec or 0.0) + (throughput.tx_bytes_per_sec or 0.0) > 0.0


def _total(throughput: NetworkThroughput | None) -> float:
    """Total throughput used for descending sort order."""
    if throughput is None:
        return 0.0
    return (throughput.rx_bytes_per_sec or 0.0) + (throughput.tx_bytes_per_sec or 0.0)


class NetworkWidget(QWidget):
    """Compact panel: aggregate Download/Upload plus a grouped interface list."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame, layout = panel_host(self, "NETWORK")

        down_caption = QLabel("Download")
        down_caption.setObjectName("muted")
        down_caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        up_caption = QLabel("Upload")
        up_caption.setObjectName("muted")
        up_caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._down = QLabel("N/A")
        self._down.setObjectName("valueBig")
        self._down.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self._up = QLabel("N/A")
        self._up.setObjectName("valueBig")
        self._up.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

        caption_row = QHBoxLayout()
        caption_row.addWidget(down_caption, 1)
        caption_row.addWidget(up_caption, 1)
        value_row = QHBoxLayout()
        value_row.addWidget(self._down, 1)
        value_row.addWidget(self._up, 1)

        layout.addLayout(caption_row)
        layout.addLayout(value_row)

        self._interface_container = QWidget()
        self._rows: list[QWidget] = []
        self._grid = QGridLayout(self._interface_container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(4)

        layout.addWidget(self._interface_container)

        self._show_all = False
        self._toggle = QPushButton("Show all interfaces")
        self._toggle.setObjectName("link")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._toggle.clicked.connect(self._on_toggle)
        toggle_row = QHBoxLayout()
        toggle_row.addStretch(1)
        toggle_row.addWidget(self._toggle)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        self._snapshot: NetworkSnapshot | None = None
        self._render()

    def _on_toggle(self) -> None:
        self._set_show_all(not self._show_all)

    def set_show_all(self, show: bool) -> None:
        """Expose idle/zero-throughput interfaces when ``show`` is True."""
        self._set_show_all(show)

    def _set_show_all(self, show: bool) -> None:
        self._show_all = show
        self._toggle.setText("Hide idle interfaces" if show else "Show all interfaces")
        self._render()

    def set_snapshot(self, snapshot: NetworkSnapshot | None) -> None:
        """Refresh the aggregate rates and the grouped interface list."""
        self._snapshot = snapshot
        self._render()

    def _clear_rows(self) -> None:
        for widget in self._rows:
            self._grid.removeWidget(widget)
            widget.deleteLater()
        self._rows = []

    def _render(self) -> None:
        self._down.setText("N/A")
        self._up.setText("N/A")
        snapshot = self._snapshot
        if snapshot is not None:
            agg = snapshot.aggregate_throughput
            self._down.setText(format_throughput(agg.rx_bytes_per_sec))
            self._up.setText(format_throughput(agg.tx_bytes_per_sec))

        self._clear_rows()
        if snapshot is None or not snapshot.interfaces:
            self._add_span_row("No network data")
            return

        grouped: dict[str, list] = {category: [] for category in CATEGORY_ORDER}
        for interface in snapshot.interfaces:
            throughput = snapshot.interface_throughput.get(interface.name)
            grouped.setdefault(classify_interface(interface.name), []).append(
                (interface, throughput)
            )

        active_count = 0
        entries: list = []
        for category in CATEGORY_ORDER:
            for interface, throughput in grouped.get(category, []):
                visible = self._show_all or _is_active(throughput)
                if not visible:
                    continue
                if _is_active(throughput):
                    active_count += 1
                entries.append((category, interface, throughput))

        if not entries:
            # No active traffic (and the user hasn't expanded everything).
            self._add_span_row("No active network traffic")
            return

        # Rebuild interface rows grouped by category, sorted by activity.
        for category in CATEGORY_ORDER:
            members = [e for e in entries if e[0] == category]
            if not members:
                continue
            members.sort(key=lambda e: -_total(e[2]))
            self._add_span_row(category, muted=True)
            for _, interface, throughput in members:
                self._add_interface_row(interface, throughput)

    def _add_span_row(self, text: str, muted: bool = False) -> None:
        label = QLabel(text)
        label.setObjectName("muted" if muted else "caption")
        row = self._grid.rowCount()
        self._grid.addWidget(label, row, 0, 1, 3)
        self._rows.append(label)

    def _add_interface_row(self, interface, throughput: NetworkThroughput | None) -> None:
        name = QLabel(interface.name)
        name.setObjectName("caption")
        down = self._muted(
            f"\u2193 {format_throughput(throughput.rx_bytes_per_sec if throughput else None)}"
        )
        up = self._muted(
            f"\u2191 {format_throughput(throughput.tx_bytes_per_sec if throughput else None)}"
        )
        down.setAlignment(Qt.AlignmentFlag.AlignRight)
        up.setAlignment(Qt.AlignmentFlag.AlignRight)
        row = self._grid.rowCount()
        self._grid.addWidget(name, row, 0)
        self._grid.addWidget(down, row, 1)
        self._grid.addWidget(up, row, 2)
        self._rows.extend((name, down, up))

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label