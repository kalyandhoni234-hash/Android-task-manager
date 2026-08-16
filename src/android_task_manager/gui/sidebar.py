"""Persistent sidebar navigation for the application shell.

Flat, keyboard-accessible navigation: one checkable button per page,
grouped under quiet section labels. The active page's button is the only
emphasized element (``:checked`` styling); everything else stays muted so
the hierarchy reads at a glance. No icons, no animations — the existing
GUI has no icon strategy, so none are invented.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: (section label, (page key, button text)) — the real destinations only.
SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("OVERVIEW", (("overview", "Overview"),)),
    ("MONITOR", (("processes", "Processes"), ("network", "Network"))),
    ("SECURITY", (("baseline", "Baseline"), ("findings", "Findings"))),
    ("DEVICE", (("device", "Device"), ("health", "Health"), ("diagnostics", "Diagnostics"))),
)

#: The page shown when the dashboard first appears.
DEFAULT_PAGE = "overview"


class Sidebar(QWidget):
    """The persistent left-hand navigation column."""

    #: (page key) the user asked to navigate to a page.
    page_requested = Signal(str)
    #: The user asked to open the diagnostics dialog (not a page).
    diagnostics_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(208)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(2)

        brand = QLabel("ANDROID\nTASK MANAGER")
        brand.setObjectName("appTitle")
        brand.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(brand)
        layout.addSpacing(10)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for section, items in SECTIONS:
            label = QLabel(section)
            label.setObjectName("navSection")
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
            layout.addSpacing(2)
            for key, text in items:
                button = QPushButton(text)
                button.setObjectName("navButton")
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                button.setAccessibleName(f"{text} page")
                button.clicked.connect(lambda checked=False, k=key: self._on_clicked(k))
                self._group.addButton(button)
                self._buttons[key] = button
                layout.addWidget(button)
            layout.addSpacing(8)
        layout.addStretch(1)

        # Diagnostics Log is an action, not a page: it stays outside the
        # page button group so it can never be the "active page". (The
        # "Diagnostics" page button lives in the DEVICE section above.)
        system_label = QLabel("SYSTEM")
        system_label.setObjectName("navSection")
        system_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(system_label)
        layout.addSpacing(2)
        self.diagnostics_button = QPushButton("Diagnostic Log")
        self.diagnostics_button.setObjectName("navButton")
        self.diagnostics_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.diagnostics_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.diagnostics_button.setAccessibleName("Diagnostic Log")
        self.diagnostics_button.clicked.connect(self.diagnostics_requested.emit)
        layout.addWidget(self.diagnostics_button)

    def _on_clicked(self, key: str) -> None:
        self.set_active(key)
        self.page_requested.emit(key)

    def set_active(self, key: str) -> None:
        """Mark *key* as the active page; only that button is checked."""
        for page_key, button in self._buttons.items():
            button.setChecked(page_key == key)

    def active_page(self) -> str:
        """The currently checked page key, or ``DEFAULT_PAGE`` when none."""
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return DEFAULT_PAGE

    def button(self, key: str) -> QPushButton:
        """The navigation button for a page key (tests / accessibility)."""
        return self._buttons[key]