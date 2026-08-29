"""Copilot page — AI assistant panel.

Sidebar-accessible page with context indicator, scrollable chat, and input
field. Matches the existing dark theme design.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..copilot.models import CopilotMessage, CopilotRole


class CopilotPage(QWidget):
    """The Copilot panel — chat interaction with device context."""

    chat_requested = Signal(str)
    navigate_requested = Signal(str)
    configure_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("copilotPage")
        self._messages: list[CopilotMessage] = []
        self._configured = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel("COPILOT")
        title.setObjectName("sectionTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(title)

        subtitle = QLabel("Ask anything about your device")
        subtitle.setObjectName("fieldLabel")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(subtitle)

        self._context_frame = QFrame()
        self._context_frame.setObjectName("panel")
        ctx_layout = QVBoxLayout(self._context_frame)
        ctx_layout.setContentsMargins(12, 8, 12, 8)
        self._context_label = QLabel("No device connected")
        self._context_label.setObjectName("fieldLabel")
        self._context_label.setTextFormat(Qt.TextFormat.PlainText)
        self._context_label.setWordWrap(True)
        ctx_layout.addWidget(self._context_label)
        root.addWidget(self._context_frame)

        self._config_banner = QFrame()
        self._config_banner.setObjectName("panel")
        banner_layout = QVBoxLayout(self._config_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        banner_layout.setSpacing(8)
        self._config_label = QLabel("Gemini API key not configured.")
        self._config_label.setObjectName("fieldLabel")
        self._config_label.setTextFormat(Qt.TextFormat.PlainText)
        self._config_label.setWordWrap(True)
        banner_layout.addWidget(self._config_label)
        self._configure_btn = QPushButton("Configure Gemini")
        self._configure_btn.setObjectName("primary")
        self._configure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._configure_btn.clicked.connect(self.configure_requested.emit)
        banner_layout.addWidget(self._configure_btn)
        root.addWidget(self._config_banner)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setObjectName("copilotScroll")
        self._messages_container = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_container)
        self._messages_layout.setContentsMargins(0, 0, 0, 0)
        self._messages_layout.setSpacing(8)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages_container)
        root.addWidget(self._scroll, stretch=1)

        self._loading_label = QLabel("")
        self._loading_label.setObjectName("fieldLabel")
        self._loading_label.setTextFormat(Qt.TextFormat.PlainText)
        self._loading_label.setVisible(False)
        root.addWidget(self._loading_label)

        self._quick_prompts = QHBoxLayout()
        self._quick_prompts.setSpacing(6)
        for text in (
            "Why is my phone slow?",
            "Optimize for gaming",
            "What's using my RAM?",
            "Why is my battery draining?",
            "Explain my health",
        ):
            btn = QPushButton(text)
            btn.setObjectName("copilotQuick")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(text)
            btn.clicked.connect(
                lambda _=False, t=text: self.set_quick_prompt(t)
            )
            self._quick_prompts.addWidget(btn)
        self._quick_prompts.addStretch(1)
        root.addLayout(self._quick_prompts)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask about your device...")
        self._input.setObjectName("copilotInput")
        self._input.returnPressed.connect(self._on_send)
        input_row.addWidget(self._input, stretch=1)
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("primary")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._send_btn)
        root.addLayout(input_row)

        self._add_system_message(
            "Welcome to Android Task Manager Copilot. "
            "I can help you understand your device, diagnose problems, "
            "and explain what you are seeing in the application."
        )

    def set_configured(self, configured: bool) -> None:
        """Show or hide the configuration banner."""
        self._configured = configured
        self._config_banner.setVisible(not configured)

    def set_quick_prompt(self, text: str) -> None:
        """Populate the input with a quick-prompt text and focus it."""
        self._input.setText(text)
        self._input.setFocus()

    def update_context(
        self,
        device_label: str | None,
        connected: bool,
        page: str,
        cpu_percent: float | None = None,
        memory_percent: float | None = None,
        battery_percent: float | None = None,
        network_connected: bool | None = None,
    ) -> None:
        """Update the context indicator bar."""
        parts: list[str] = []
        if connected and device_label:
            parts.append(device_label)
        elif not connected:
            parts.append("No device connected")
        if cpu_percent is not None:
            parts.append(f"CPU {cpu_percent:.0f}%")
        if memory_percent is not None:
            parts.append(f"RAM {memory_percent:.0f}%")
        if battery_percent is not None:
            parts.append(f"Battery {battery_percent:.0f}%")
        if connected and network_connected is not None:
            parts.append("Network" if network_connected else "No network")
        elif connected:
            parts.append("Network unknown")
        parts.append(f"Page: {page}")
        self._context_label.setText(" | ".join(parts))

    def on_response(self, query: str, answer: str, suggestions: tuple[str, ...] = ()) -> None:
        """Display a copilot response."""
        self._add_assistant_message(answer)
        if suggestions:
            sug_text = "Suggestions:\n" + "\n".join(f"  - {s}" for s in suggestions)
            self._add_system_message(sug_text)
        self._set_loading(False)

    def on_error(self, error: str) -> None:
        """Display an error message."""
        self._add_system_message(f"Error: {error}")
        self._set_loading(False)

    def _on_send(self) -> None:
        query = self._input.text().strip()
        if not query:
            return
        if not self._configured:
            self._add_system_message(
                "Gemini API key not configured. "
                "Click 'Configure Gemini' to set up your API key."
            )
            return
        self._input.clear()
        self._add_user_message(query)
        self._set_loading(True)
        self.chat_requested.emit(query)

    def _add_user_message(self, content: str) -> None:
        msg = CopilotMessage(
            role=CopilotRole.USER,
            content=content,
            timestamp=time.time(),
        )
        self._messages.append(msg)
        self._render_bubble("You", content)

    def _add_assistant_message(self, content: str) -> None:
        msg = CopilotMessage(
            role=CopilotRole.ASSISTANT,
            content=content,
            timestamp=time.time(),
        )
        self._messages.append(msg)
        self._render_bubble("Copilot", content)

    def _add_system_message(self, content: str) -> None:
        self._render_bubble("System", content, object_name="copilotSystem")

    def _render_bubble(
        self, role: str, content: str, object_name: str = "copilotBubble"
    ) -> None:
        frame = QFrame()
        frame.setObjectName(object_name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        role_label = QLabel(role.upper())
        role_label.setObjectName("sectionTitle")
        role_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label.setObjectName("copilotContent")
        layout.addWidget(role_label)
        layout.addWidget(content_label)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, frame)
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_loading(self, loading: bool) -> None:
        self._loading_label.setText("Thinking..." if loading else "")
        self._loading_label.setVisible(loading)
        self._send_btn.setEnabled(not loading)
        self._input.setEnabled(not loading)

    def conversation_history(self) -> tuple[CopilotMessage, ...]:
        return tuple(self._messages)
