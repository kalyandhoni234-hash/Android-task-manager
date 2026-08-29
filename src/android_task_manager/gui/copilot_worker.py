"""CopilotWorker — runs LLM calls off the GUI thread.

Follows the exact same pattern as ActionWorker / UpdateWorker:
QObject + moveToThread + Signal/Slot.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from ..copilot.models import CopilotRequest, CopilotResult
from ..copilot.providers import build_provider
from ..copilot.service import handle_request
from ..copilot.settings import CopilotConfig

logger = logging.getLogger("android_task_manager.copilot")


class CopilotWorker(QObject):
    """Runs LLM calls off the GUI thread."""

    #: (CopilotResult) response ready or typed failure
    response_ready = Signal(object)
    #: (bool, str) test connection result (success, message)
    test_connection_result = Signal(bool, str)

    def __init__(self, config: CopilotConfig) -> None:
        super().__init__()
        self._config = config
        self._provider = build_provider(
            config.endpoint, config.api_key, config.provider
        )
        self._busy = False

    def is_busy(self) -> bool:
        return self._busy

    def update_config(self, config: CopilotConfig) -> None:
        self._config = config
        self._provider = build_provider(
            config.endpoint, config.api_key, config.provider
        )

    @Slot(object)
    def request_chat(self, request: CopilotRequest) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            if not self._config.is_configured:
                self.response_ready.emit(
                    CopilotResult(
                        success=False,
                        error=(
                            "Gemini API key not configured. "
                            "Open Copilot Settings to add your API key."
                        ),
                        request_query=request.query,
                    )
                )
                return
            result = handle_request(
                request,
                self._provider,
                model=self._config.model,
                temperature=self._config.temperature,
                timeout=self._config.timeout,
            )
        finally:
            self._busy = False
        self.response_ready.emit(result)

    @Slot(object)
    def request_test_connection(self, config: CopilotConfig) -> None:
        """Test the Gemini connection with a minimal request."""
        if self._busy:
            self.test_connection_result.emit(False, "Worker busy. Please wait.")
            return
        self._busy = True
        try:
            if not config.api_key:
                self.test_connection_result.emit(
                    False, "No API key provided."
                )
                return
            provider = build_provider(
                config.endpoint, config.api_key, config.provider
            )
            test_request = CopilotRequest(
                query="Hello",
                context=__import__(
                    "android_task_manager.copilot.models", fromlist=["CopilotContext"]
                ).CopilotContext(current_page="overview", connected=False),
            )
            result = handle_request(
                test_request,
                provider,
                model=config.model,
                temperature=0.3,
                timeout=config.timeout,
            )
            if result.success:
                self.test_connection_result.emit(
                    True, "Gemini connection successful."
                )
            else:
                error = result.error or "Unknown error"
                if "authentication" in error.lower() or "denied" in error.lower():
                    self.test_connection_result.emit(False, "API key is invalid.")
                elif "timed out" in error.lower():
                    self.test_connection_result.emit(
                        False, "Gemini request timed out."
                    )
                elif "unavailable" in error.lower():
                    self.test_connection_result.emit(
                        False, "Gemini is temporarily unavailable."
                    )
                elif "model not found" in error.lower():
                    self.test_connection_result.emit(
                        False, "Model is unavailable."
                    )
                elif "could not connect" in error.lower():
                    self.test_connection_result.emit(
                        False, "Could not connect to Gemini."
                    )
                else:
                    self.test_connection_result.emit(False, error)
        except Exception:
            logger.exception("Test connection failed")
            self.test_connection_result.emit(
                False, "Unexpected error during connection test."
            )
        finally:
            self._busy = False
