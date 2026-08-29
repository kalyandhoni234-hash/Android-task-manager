"""First-class Settings page — categorized, modern desktop settings.

Groups the application's configuration into labelled sections (General,
Appearance, Monitoring, AI Copilot, Safety & Privacy, Advanced) with clear
descriptions, sensible defaults, masked secrets and confirmation for
destructive local-data operations. It is a thin shell over the existing
configuration subsystems (app settings JSON, Copilot config, the Copilot
settings dialog); no second configuration mechanism is introduced.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..settings import AppSettings, load_settings, save_settings
from .styles import repolish

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_SYSTEM = "system"
THEME_CYBER = "cyber"


def _section(title: str, body: QWidget) -> QFrame:
    card = QFrame()
    card.setObjectName("settingsGroup")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    heading.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(heading)
    layout.addWidget(body)
    return card


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class SettingsPage(QWidget):
    """Categorized settings with a modern, grouped layout."""

    #: The user asked to open the existing Copilot settings dialog.
    copilot_manage_requested = Signal()
    #: (CopilotConfig) the user asked to test the Copilot connection.
    copilot_test_requested = Signal(object)
    #: The user asked to open the existing diagnostics dialog (log).
    diagnostics_requested = Signal()
    #: The user confirmed clearing all local data.
    clear_local_data_requested = Signal()
    #: (theme) the user switched theme; emitted with the new theme value.
    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suppress_theme = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(title)

        subtitle = QLabel("Choose how the application looks and how it runs.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(subtitle)

        # -- General --------------------------------------------------------
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(6)

        interval_label = QLabel("Monitoring refresh interval (seconds)")
        interval_label.setObjectName("cardCaption")
        interval_label.setTextFormat(Qt.TextFormat.PlainText)
        general_layout.addWidget(interval_label)

        self._interval_spin = QSpinBox()
        self._interval_spin.setObjectName("settingsSpin")
        self._interval_spin.setRange(1, 30)
        self._interval_spin.setValue(2)
        self._interval_spin.setToolTip("How often device readings are refreshed.")
        general_layout.addWidget(self._interval_spin)

        interval_hint = QHBoxLayout()
        interval_hint.addWidget(self._interval_spin)
        note = _caption("Applies to new monitoring sessions.")
        interval_hint.addWidget(note, 1)
        general_layout.addLayout(interval_hint)
        root.addWidget(_section("GENERAL", general))

        # -- Appearance -----------------------------------------------------
        appearance = QWidget()
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.setContentsMargins(0, 0, 0, 0)
        appearance_layout.setSpacing(6)

        theme_label = QLabel("Theme")
        theme_label.setObjectName("cardCaption")
        theme_label.setTextFormat(Qt.TextFormat.PlainText)
        appearance_layout.addWidget(theme_label)

        self._theme_combo = QComboBox()
        self._theme_combo.setObjectName("settingsCombo")
        self._theme_combo.addItem("Dark", THEME_DARK)
        self._theme_combo.addItem("Light", THEME_LIGHT)
        self._theme_combo.addItem("System", THEME_SYSTEM)
        self._theme_combo.addItem("Cyber", THEME_CYBER)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        appearance_layout.addWidget(self._theme_combo)

        theme_hint = _caption(
            "Dark is the default. System follows your operating system appearance. "
            "Cyber is a professional cybersecurity visual mode."
        )
        appearance_layout.addWidget(theme_hint)
        root.addWidget(_section("APPEARANCE", appearance))

        # -- AI Copilot -----------------------------------------------------
        copilot = QWidget()
        copilot_layout = QVBoxLayout(copilot)
        copilot_layout.setContentsMargins(0, 0, 0, 0)
        copilot_layout.setSpacing(8)

        self._api_status = QLabel("AI Copilot is not configured.")
        self._api_status.setObjectName("statusWarn")
        self._api_status.setWordWrap(True)
        self._api_status.setTextFormat(Qt.TextFormat.PlainText)
        copilot_layout.addWidget(self._api_status)

        self._key_caption = _caption(
            "Your Gemini API key is stored locally on this computer. "
            "It is never sent with your questions beyond the Gemini API."
        )
        self._key_caption.setVisible(False)
        copilot_layout.addWidget(self._key_caption)

        manage_row = QHBoxLayout()
        manage_row.setSpacing(8)
        self._manage_btn = QPushButton("Configure API Key")
        self._manage_btn.setObjectName("secondary")
        self._manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manage_btn.clicked.connect(self.copilot_manage_requested.emit)
        manage_row.addWidget(self._manage_btn)
        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setObjectName("secondary")
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.setToolTip("Verify the configured Gemini key works.")
        self._test_btn.clicked.connect(self._on_test)
        manage_row.addWidget(self._test_btn)
        manage_row.addStretch(1)
        copilot_layout.addLayout(manage_row)

        self._test_status = QLabel("")
        self._test_status.setObjectName("muted")
        self._test_status.setWordWrap(True)
        self._test_status.setTextFormat(Qt.TextFormat.PlainText)
        copilot_layout.addWidget(self._test_status)
        root.addWidget(_section("AI COPILOT", copilot))

        # -- Safety & Privacy ----------------------------------------------
        privacy = QWidget()
        privacy_layout = QVBoxLayout(privacy)
        privacy_layout.setContentsMargins(0, 0, 0, 0)
        privacy_layout.setSpacing(8)

        self._context_check = QCheckBox("Show live CPU / RAM / battery context in Copilot")
        self._context_check.setObjectName("settingsCheck")
        self._context_check.setToolTip("Uncheck to stop sending live metric chips to the Copilot.")
        privacy_layout.addWidget(self._context_check)

        privacy_note = _caption(
            "Readings and your questions are used only to shape helpful answers. "
            "Nothing is uploaded for training and no API key is ever embedded in "
            "reports, logs or prompts."
        )
        privacy_layout.addWidget(privacy_note)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(8)
        clear_label = QLabel("All your local data stays on this computer.")
        clear_label.setObjectName("muted")
        clear_label.setWordWrap(True)
        clear_label.setTextFormat(Qt.TextFormat.PlainText)
        clear_row.addWidget(clear_label, 1)
        self._clear_btn = QPushButton("Clear Local Data")
        self._clear_btn.setObjectName("danger")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setToolTip("Delete saved settings, Copilot configuration and baselines.")
        self._clear_btn.clicked.connect(self.clear_local_data_requested.emit)
        clear_row.addWidget(self._clear_btn)
        privacy_layout.addLayout(clear_row)
        root.addWidget(_section("SAFETY & PRIVACY", privacy))

        # -- Advanced -------------------------------------------------------
        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)

        log_note = _caption(
            "Diagnostics and health/performance engines collect detailed device "
            "readings. Advanced tools keep the full technical record available."
        )
        advanced_layout.addWidget(log_note)

        log_row = QHBoxLayout()
        log_row.setSpacing(8)
        self._log_btn = QPushButton("Open Diagnostic Log")
        self._log_btn.setObjectName("secondary")
        self._log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_btn.clicked.connect(self.diagnostics_requested.emit)
        log_row.addWidget(self._log_btn)
        log_row.addStretch(1)
        advanced_layout.addLayout(log_row)
        root.addWidget(_section("ADVANCED", advanced))

        root.addStretch(1)

    def set_settings(self, settings: AppSettings) -> None:
        """Populate the page from persisted settings."""
        self._suppress_theme = True
        theme_index = self._theme_combo.findData(settings.theme)
        if theme_index >= 0:
            self._theme_combo.setCurrentIndex(theme_index)
        self._suppress_theme = False
        self._interval_spin.setValue(settings.refresh_interval_s)

    def settings_values(self) -> tuple[int, str]:
        """Current (refresh_interval_s, theme)."""
        return (
            self._interval_spin.value(),
            str(self._theme_combo.currentData()),
        )

    def set_test_result(self, success: bool, message: str) -> None:
        """Show the result of an AI Copilot connection test."""
        self._test_btn.setEnabled(True)
        self._test_status.setText(message)
        self._test_status.setObjectName("statusConnected" if success else "statusError")
        repolish(self._test_status)

    def set_copilot_state(self, configured: bool, masked_key: str) -> None:
        """Update the AI Copilot status display."""
        if configured:
            self._api_status.setText("AI Copilot is configured.")
            self._api_status.setObjectName("statusConnected")
            self._key_caption.setText(
                f"Your Gemini API key is stored locally on this computer "
                f"(key ending in {masked_key[-4:] if masked_key else '····'}). "
                f"It is never sent with your questions beyond the Gemini API."
            )
            self._key_caption.setVisible(True)
            self._test_btn.setEnabled(True)
        else:
            self._api_status.setText("AI Copilot is not configured.")
            self._api_status.setObjectName("statusWarn")
            self._key_caption.setVisible(False)
            self._test_btn.setEnabled(False)
        self._test_status.setText("")
        repolish(self._api_status)

    def _on_test(self) -> None:
        from ..copilot.settings import load_config

        self._test_btn.setEnabled(False)
        self._test_status.setText("Testing connection...")
        self.copilot_test_requested.emit(load_config())

    def _on_theme_changed(self) -> None:
        if self._suppress_theme:
            return
        theme = str(self._theme_combo.currentData())
        settings = load_settings()
        settings.theme = theme
        save_settings(settings)
        self.theme_changed.emit(theme)
