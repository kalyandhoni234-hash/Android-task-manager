"""Copilot settings dialog — user-owned Gemini API key configuration.

Modal dialog for configuring the Copilot provider, API key, and model.
API key is displayed as masked after saving. Test Connection runs
off the GUI thread via CopilotWorker.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..copilot.settings import CopilotConfig, save_config


class CopilotSettingsDialog(QDialog):
    """Copilot settings: provider, API key, model, test connection."""

    #: Emitted with the updated config after save
    config_saved = Signal(object)
    #: Emitted to request a test connection (config, provider)
    test_connection_requested = Signal(object)

    def __init__(self, config: CopilotConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Copilot Settings")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Copilot Settings")
        title.setObjectName("pageTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(title)

        subtitle = QLabel(
            "Your Gemini API key is stored locally on this device and is "
            "used to access Gemini for Copilot."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(subtitle)

        provider_label = QLabel("Provider")
        provider_label.setObjectName("cardCaption")
        provider_label.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(provider_label)
        self._provider_edit = QLineEdit(config.provider)
        self._provider_edit.setPlaceholderText("gemini")
        self._provider_edit.setObjectName("copilotInput")
        self._provider_edit.setReadOnly(True)
        root.addWidget(self._provider_edit)

        model_label = QLabel("Model")
        model_label.setObjectName("cardCaption")
        model_label.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(model_label)
        self._model_edit = QLineEdit(config.model)
        self._model_edit.setPlaceholderText("gemini-2.0-flash")
        self._model_edit.setObjectName("copilotInput")
        root.addWidget(self._model_edit)

        api_key_label = QLabel("API Key")
        api_key_label.setObjectName("cardCaption")
        api_key_label.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(api_key_label)
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText("Enter your Gemini API key...")
        self._api_key_edit.setObjectName("copilotInput")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        root.addWidget(self._api_key_edit)

        if config.api_key:
            self._api_key_edit.setText(config.api_key)

        self._key_status = QLabel("")
        self._key_status.setObjectName("muted")
        self._key_status.setTextFormat(Qt.TextFormat.PlainText)
        if config.api_key:
            self._key_status.setText(
                f"Key saved: {config.masked_api_key()}"
            )
        root.addWidget(self._key_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._test_btn = QPushButton("Test Connection")
        self._test_btn.setObjectName("secondary")
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(self._test_btn)

        self._clear_btn = QPushButton("Clear Key")
        self._clear_btn.setObjectName("secondary")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)

        btn_row.addStretch(1)

        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primary")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

        self._status = QLabel("")
        self._status.setObjectName("muted")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._status)

    def _on_save(self) -> None:
        self._config.provider = self._provider_edit.text().strip() or "gemini"
        self._config.model = self._model_edit.text().strip() or "gemini-2.0-flash"
        # An empty key field must not silently wipe a previously saved key;
        # clearing is an explicit action via the Clear Key button. If the field
        # is empty we keep whatever key is already configured.
        key = self._api_key_edit.text().strip()
        if key:
            self._config.api_key = key
        save_config(self._config)
        if self._config.api_key:
            self._key_status.setText(f"Key saved: {self._config.masked_api_key()}")
        else:
            self._key_status.setText("No API key saved.")
        self._status.setText("Configuration saved.")
        self.config_saved.emit(self._config)

    def _on_clear(self) -> None:
        self._config.api_key = ""
        self._api_key_edit.clear()
        self._key_status.setText("")
        save_config(self._config)
        self._status.setText("API key cleared.")
        self.config_saved.emit(self._config)

    def _on_test(self) -> None:
        self._status.setText("Testing connection...")
        self._test_btn.setEnabled(False)
        self._config.provider = self._provider_edit.text().strip() or "gemini"
        self._config.model = self._model_edit.text().strip() or "gemini-2.0-flash"
        self._config.api_key = self._api_key_edit.text().strip()
        self.test_connection_requested.emit(self._config)

    def on_test_result(self, success: bool, message: str) -> None:
        self._test_btn.setEnabled(True)
        self._status.setText(message)

    def get_config(self) -> CopilotConfig:
        return self._config
