"""Copilot service — orchestrates prompt building, provider call, response parsing.

Stateless logic layer. The CopilotWorker QObject calls these functions.
"""

from __future__ import annotations

import logging
import re

from .models import CopilotRequest, CopilotResponse, CopilotResult
from .prompts import build_messages, parse_response
from .providers import LLMProvider, LLMProviderError

logger = logging.getLogger("android_task_manager.copilot")


def _friendly_error(exc: LLMProviderError, provider_name: str) -> str:
    """Map a provider error to a human-readable GUI message."""
    msg = str(exc)

    if "HTTP 401" in msg or "Unauthorized" in msg or "API key not valid" in msg:
        if provider_name == "gemini":
            return (
                "AI Copilot authentication failed. "
                "Please contact the application maintainer."
            )
        if provider_name == "ollama":
            return (
                "Ollama authentication failed. "
                "Check that Ollama is running and the endpoint is correct."
            )
        return (
            "Authentication failed. "
            "Check your Copilot API key and provider configuration."
        )

    if "HTTP 403" in msg or "Forbidden" in msg:
        return "AI Copilot access was denied."

    if "HTTP 404" in msg or "Not Found" in msg:
        if provider_name == "gemini":
            return (
                "AI Copilot model not found. "
                "Please contact the application maintainer."
            )
        return (
            "Endpoint or model not found. "
            "Verify your Copilot base URL and model name are correct."
        )

    if "HTTP 429" in msg:
        return "AI Copilot is temporarily rate limited. Please try again later."

    code_match = re.search(r"HTTP (\d{3})", msg)
    if code_match:
        code = int(code_match.group(1))
        if 500 <= code < 600:
            return "Gemini is temporarily unavailable. Please try again."

    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "AI Copilot request timed out."

    if "Connection refused" in msg:
        return (
            "Could not connect to provider. "
            "Verify the base URL and ensure the service is running."
        )

    return msg


def handle_request(
    request: CopilotRequest,
    provider: LLMProvider,
    *,
    model: str,
    temperature: float,
    timeout: float,
) -> CopilotResult:
    """Process a copilot request: build prompt -> call provider -> parse.

    Returns a CopilotResult with either a response or an error message.
    Never raises — all failures are captured.
    """
    try:
        messages = build_messages(
            request.query, request.context, request.conversation_history
        )
        raw = provider.chat(
            messages,
            model=model,
            temperature=temperature,
            timeout=timeout,
        )
        answer, suggestions, confidence, related_pages = parse_response(raw)
        response = CopilotResponse(
            answer=answer,
            suggestions=suggestions,
            confidence=confidence,
            related_pages=related_pages,
        )
        return CopilotResult(
            success=True,
            response=response,
            request_query=request.query,
        )
    except LLMProviderError as exc:
        logger.warning("Copilot provider error: %s", exc)
        return CopilotResult(
            success=False,
            error=_friendly_error(exc, provider.name),
            request_query=request.query,
        )
    except Exception:
        logger.exception("Unexpected copilot error")
        return CopilotResult(
            success=False,
            error="Unexpected error. Please try again.",
            request_query=request.query,
        )
