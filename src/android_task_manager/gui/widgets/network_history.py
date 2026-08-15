"""Network history graph: recent Download and Upload throughput.

Two series fed purely from the aggregate rates already present in each
``NetworkSnapshot`` — no additional ADB commands are ever issued for the
graph. The y-axis rescales dynamically to the window peak (rates vary by
orders of magnitude), guards zero-traffic windows with a floor of 1 B/s,
and skips ``None`` samples so a missing delta is never drawn as a spike.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .history_base import HistoryPlotWidget


class NetworkHistoryWidget(QWidget):
    """Bounded sliding window of download/upload throughput (B/s)."""

    def __init__(self, max_samples: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = HistoryPlotWidget(
            caption="recent network traffic",
            colors=[QColor("#3d9be9"), QColor("#7ac74f")],
            max_samples=max_samples,
            scale="rate",
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)
        self.setMinimumHeight(self._plot.minimumHeight())

    @property
    def download_samples(self) -> list[float]:
        """Copy of the download history (oldest first)."""
        return self._plot.samples(0)

    @property
    def upload_samples(self) -> list[float]:
        """Copy of the upload history (oldest first)."""
        return self._plot.samples(1)

    def add_sample(self, download: float | None, upload: float | None) -> None:
        """Append one down/up pair; ``None`` members are skipped."""
        self._plot.add_sample(0, download)
        self._plot.add_sample(1, upload)