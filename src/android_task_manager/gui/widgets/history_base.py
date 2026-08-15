"""Shared QPainter history plot with a bounded sliding window.

The CPU history approach generalised for the memory / network / battery
graphs: one custom-painted widget, zero charting dependencies, a fixed-size
window (never unlimited retention), and ``None`` samples skipped instead of
plotted. Two scales are supported:

* ``percent`` — a fixed 0-100 range (memory available %, battery level).
* ``rate``   — a dynamic range scaled to the largest recent value
  (network bytes/sec, where peaks vary by orders of magnitude).

Widgets that embed this plot only ever feed it normalized snapshot values;
it never talks to adb.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ...terminal.renderer import format_throughput

_GRID_COLOR = QColor("#2a323c")
_TEXT_COLOR = QColor("#7a8794")

_LEFT_MARGIN = 34
_RIGHT_MARGIN = 8
_TOP_MARGIN = 6
_BOTTOM_MARGIN = 16


#: Grid rows for the fixed percent scale: 100/75/50/25/0.
_PERCENT_LEVELS = (1.0, 0.75, 0.5, 0.25, 0.0)


class _RateScale:
    """Dynamic y-axis that rescales to the largest value in the window."""

    def __init__(self) -> None:
        self._max = 1.0

    def prepare(self, series: list[list[float]]) -> None:
        peak = max((max(values, default=0.0) for values in series), default=0.0)
        self._max = max(1.0, peak)

    def max_value(self) -> float:
        return self._max

    def levels(self, series: list[list[float]]) -> list[tuple[float, str]]:
        self.prepare(series)
        return [
            (1.0, format_throughput(self._max)),
            (0.5, format_throughput(self._max / 2)),
            (0.0, "0"),
        ]

    def clamp(self, value: float) -> float:
        return min(max(value, 0.0), self._max)


class _PercentScale:
    """Fixed 0-100 scale for percentages."""

    def levels(self, series: list[list[float]]) -> list[tuple[float, str]]:
        return [(level, f"{round(level * 100)}%") for level in _PERCENT_LEVELS]

    def clamp(self, value: float) -> float:
        return min(max(value, 0.0), 100.0)

    def max_value(self) -> float:
        return 100.0


class HistoryPlotWidget(QWidget):
    """Plots 1-2 named series over a bounded sliding window.

    The first series is filled underneath its line; additional series are
    drawn as plain polylines. ``None`` samples (no baseline yet, missing
    snapshot, permission-denied) are ignored, never plotted as bogus dips.
    """

    def __init__(
        self,
        caption: str,
        colors: list[QColor],
        max_samples: int = 30,
        scale: str = "percent",
        parent: QWidget | None = None,
        minimum_height: int = 64,
    ) -> None:
        super().__init__(parent)
        self._caption = caption
        self._colors = [QColor(color) for color in colors]
        self._max_samples = max(2, max_samples)
        self._series: list[list[float]] = [[] for _ in self._colors]
        assert self._series, "at least one series is required"
        self._scale = _RateScale() if scale == "rate" else _PercentScale()
        self._fill = QColor(self._colors[0])
        self._fill.setAlpha(46)
        self.setMinimumHeight(minimum_height)
        self.setMinimumWidth(120)

    # ------------------------------------------------------------------
    # Data API (bounded, oldest-first)
    # ------------------------------------------------------------------

    def samples(self, series_index: int = 0) -> list[float]:
        """Copy of one series' retained history (oldest first)."""
        return list(self._series[series_index])

    def series_count(self) -> int:
        return len(self._colors)

    def add_sample(self, series_index: int, value: float | None) -> None:
        """Append one sample, keeping the per-series sliding window.

        ``None`` is ignored: a missing value must never become a fabricated
        drop to zero on the graph.
        """
        if value is None:
            return
        target = self._series[series_index]
        target.append(float(value))
        overflow = len(target) - self._max_samples
        if overflow > 0:
            del target[:overflow]
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
        self._draw_series(painter, plot)
        self._draw_caption(painter, plot)
        painter.end()

    def _draw_grid(self, painter: QPainter, plot: QRect) -> None:
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)

        levels = self._scale.levels(self._series)
        for fraction, label in levels:
            y = plot.bottom() - fraction * plot.height()
            painter.setPen(QPen(_GRID_COLOR, 1))
            painter.drawLine(plot.left(), int(y), plot.right(), int(y))
            painter.setPen(QPen(_TEXT_COLOR, 1))
            painter.drawText(
                QRect(0, int(y) - 5, _LEFT_MARGIN - 2, 12),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _draw_series(self, painter: QPainter, plot: QRect) -> None:
        for index, values in enumerate(self._series):
            if not values:
                continue
            points = self._points(plot, values)
            if index == 0:
                path = QPainterPath(points.first())
                for point_index in range(1, len(points)):
                    path.lineTo(points[point_index])
                path.lineTo(QPointF(points.last().x(), plot.bottom()))
                path.lineTo(QPointF(points.first().x(), plot.bottom()))
                path.closeSubpath()
                painter.fillPath(path, self._fill)
            painter.setPen(QPen(self._colors[index], 2))
            painter.drawPolyline(points)

    def _points(self, plot: QRect, values: list[float]) -> QPolygonF:
        count = len(values)
        points = QPolygonF()
        for index, value in enumerate(values):
            x = plot.left() + (index / max(count - 1, 1)) * plot.width()
            y = plot.bottom() - (self._scale.clamp(value) / self._scale.max_value()) * plot.height()
            points.append(QPointF(x, y))
        return points

    def _draw_caption(self, painter: QPainter, plot: QRect) -> None:
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QPen(_TEXT_COLOR, 1))
        painter.drawText(
            QRect(plot.left(), plot.bottom() + 3, plot.width(), 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._caption,
        )