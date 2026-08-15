"""GUI presentation widgets. Consume normalized snapshots only."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


def panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Create a styled dashboard section with a title header.

    Every section shares one vertical rhythm (10 px) and one header
    structure: title, 1 px divider, then the section content. The divider
    is the only accent — sections stay quiet and technical.
    """
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(10)
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    layout.addWidget(label)
    rule = QFrame()
    rule.setObjectName("sectionRule")
    rule.setFixedHeight(1)
    layout.addWidget(rule)
    return frame, layout


def panel_host(parent: QWidget, title: str) -> tuple[QFrame, QVBoxLayout]:
    """Build a panel and anchor it into ``parent`` so it survives GC.

    ``panel`` alone returns a floating QFrame; without a parent its child
    widgets are destroyed once the Python reference drops. Hosting the frame
    in ``parent``'s layout guarantees the frame (and its labels) stay alive
    for the lifetime of ``parent``.
    """
    frame, layout = panel(title)
    host = QVBoxLayout(parent)
    host.setContentsMargins(0, 0, 0, 0)
    host.addWidget(frame)
    return frame, layout