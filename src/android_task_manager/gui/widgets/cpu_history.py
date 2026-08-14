"""Lightweight live CPU history graph.

A small custom-painted widget (QPainter) that draws recent aggregate CPU
utilization as a simple 0-100% line chart with a subtle grid. It consumes
the normalized CPU snapshots already emitted by the monitor; it never talks
to adb and adds no charting dependency.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

_GRID_LEVELS = (100, 75, 50, 25, 0)
_GRID_COLOR = QColor("#2a323c")
_TEXT_COLOR = QColor("#7a8794")
_LINE_COLOR = QColor("#3d9be9")
_FILL_COLOR = QColor(61, 155, 233, 46)

_LEFT_MARGIN = 30
_RIGHT_MARGIN = 8
_TOP_MARGIN = 6
_BOTTOM_MARGIN = 16


class CPUHistoryWidget(QWidget):
    """Plots recent aggregate CPU utilization values on a fixed 0-100 scale."""

    def __init__(self, max_samples: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_samples = max(2, max_samples)
        self._samples: list[float] = []
        self.setMinimumHeight(84)
        self.setObjectName("cpuHistory")

    @property
    def samples(self) -> list[float]:
        """Copy of the retained history (oldest first)."""
        return list(self._samples)

    def add_sample(self, value: float | None) -> None:
        """Append one aggregate CPU sample, keeping the sliding window.

        ``None`` (e.g. the very first snapshot has no baseline yet) is
        ignored rather than plotted.
        """
        if value is None:
            return
        self._samples.append(float(value))
        overflow = len(self._samples) - self._max_samples
        if overflow > 0:
            del self._samples[:overflow]
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        plot = QRect(
            _LEFT_MARGIN,
            _TOP_MARGIN,
            max(0, self.width() - _LEFT_MARGIN - _RIGHT_MARGIN),
            max(0, self.height() - _TOP_MARGIN - _BOTTOM_MARGIN),
        )
        if plot.width() <= 0 or plot.height() <= 0:
            painter.end()
            return

        self._draw_grid(painter, plot)
        self._draw_history(painter, plot)
        self._draw_caption(painter, plot)
        painter.end()

    def _draw_grid(self, painter: QPainter, plot: QRect) -> None:
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        for level in _GRID_LEVELS:
            y = plot.bottom() - (level / 100.0) * plot.height()
            painter.setPen(QPen(_GRID_COLOR, 1))
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
            painter.setPen(QPen(_TEXT_COLOR, 1))
            painter.drawText(
                QRect(0, int(y) - 5, _LEFT_MARGIN - 4, 12),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{level}%",
            )

    def _draw_history(self, painter: QPainter, plot: QRect) -> None:
        if not self._samples:
            return

        count = len(self._samples)
        points = QPolygonF()
        for index, value in enumerate(self._samples):
            x = plot.left() + (index / max(count - 1, 1)) * plot.width()
            y = plot.bottom() - (min(max(value, 0.0), 100.0) / 100.0) * plot.height()
            points.append(QPointF(x, y))

        path = QPainterPath(points.first())
        for index in range(1, len(points)):
            path.lineTo(points[index])
        path.lineTo(QPointF(points.last().x(), plot.bottom()))
        path.lineTo(QPointF(points.first().x(), plot.bottom()))
        path.closeSubpath()
        painter.fillPath(path, _FILL_COLOR)

        painter.setPen(QPen(_LINE_COLOR, 2))
        painter.drawPolyline(points)

    def _draw_caption(self, painter: QPainter, plot: QRect) -> None:
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QPen(_TEXT_COLOR, 1))
        painter.drawText(
            QRect(plot.left(), plot.bottom() + 3, plot.width(), 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "recent CPU history",
        )
