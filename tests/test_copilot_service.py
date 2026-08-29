"""Tests for the Copilot service orchestration."""

from __future__ import annotations

from android_task_manager.copilot.models import CopilotContext, CopilotRequest
from android_task_manager.copilot.providers import LLMProviderError
from android_task_manager.copilot.service import handle_request


def _make_request(query: str = "What is RAM?") -> CopilotRequest:
    return CopilotRequest(
        query=query,
        context=CopilotContext(
            current_page="overview",
            connected=True,
            device_label="Test",
        ),
    )


class FakeProvider:
    def __init__(self, response: str = "RAM is memory.") -> None:
        self._response = response
        self.name = "fake"

    def chat(self, messages, *, model, temperature, timeout) -> str:
        return self._response


class FailingProvider:
    def __init__(self, error: str = "Connection failed") -> None:
        self._error = error
        self.name = "failing"

    def chat(self, messages, *, model, temperature, timeout) -> str:
        raise LLMProviderError(self._error, retryable=True)


class CrashProvider:
    def __init__(self) -> None:
        self.name = "crash"

    def chat(self, messages, *, model, temperature, timeout) -> str:
        raise RuntimeError("Unexpected crash")


def test_handle_request_success() -> None:
    provider = FakeProvider("RAM is memory.")
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is True
    assert result.response is not None
    assert "RAM" in result.response.answer


def test_handle_request_provider_error() -> None:
    provider = FailingProvider("Connection refused")
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert result.error is not None
    assert "Could not connect" in result.error


def test_handle_request_unexpected_error() -> None:
    provider = CrashProvider()
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert result.error == "Unexpected error. Please try again."


def test_handle_request_preserves_query() -> None:
    provider = FakeProvider("OK")
    result = handle_request(
        _make_request("Tell me about CPU"),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.request_query == "Tell me about CPU"


def test_handle_request_with_suggestions() -> None:
    provider = FakeProvider(
        "CPU is high.\n\n"
        "Suggestions:\n"
        "- Check com.example.app\n"
        "- Review processes\n"
        "\n"
        "Confidence: high\n"
    )
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is True
    assert result.response is not None
    assert len(result.response.suggestions) == 2
    assert result.response.confidence == "high"


def test_friendly_error_401_openai() -> None:
    """HTTP 401 produces a user-friendly authentication message."""
    provider = FailingProvider("HTTP 401: Unauthorized")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "Authentication failed" in result.error
    assert "API key" in result.error
    assert "401" not in result.error


def test_friendly_error_401_ollama() -> None:
    """HTTP 401 on Ollama produces an Ollama-specific message."""
    provider = FailingProvider("HTTP 401: Unauthorized")
    provider.name = "ollama"
    result = handle_request(
        _make_request(),
        provider,
        model="llama3",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "Ollama" in result.error
    assert "401" not in result.error


def test_friendly_error_403() -> None:
    """HTTP 403 produces a permission-denied message."""
    provider = FailingProvider("HTTP 403: Forbidden")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "denied" in result.error.lower()
    assert "403" not in result.error


def test_friendly_error_404() -> None:
    """HTTP 404 produces an endpoint-not-found message."""
    provider = FailingProvider("HTTP 404: Not Found")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "not found" in result.error.lower()
    assert "404" not in result.error


def test_friendly_error_429() -> None:
    """HTTP 429 produces a rate-limit message."""
    provider = FailingProvider("HTTP 429: Too Many Requests")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "rate limited" in result.error.lower()


def test_friendly_error_timeout() -> None:
    """Timeout error produces a timeout message."""
    provider = FailingProvider("timed out")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "timed out" in result.error.lower()


def test_friendly_error_connection_refused() -> None:
    """Connection refused produces a connection message."""
    provider = FailingProvider("Connection refused")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "Could not connect" in result.error


def test_friendly_error_500() -> None:
    """HTTP 500 produces a server-error message."""
    provider = FailingProvider("HTTP 500: Internal Server Error")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "unavailable" in result.error.lower()
    assert "try again" in result.error.lower()


def test_friendly_error_401_gemini() -> None:
    """HTTP 401 on Gemini produces a maintainer-message."""
    provider = FailingProvider("HTTP 401: Unauthorized")
    provider.name = "gemini"
    result = handle_request(
        _make_request(),
        provider,
        model="gemini-2.0-flash",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "authentication failed" in result.error.lower()
    assert "maintainer" in result.error.lower()
    assert "401" not in result.error


def test_friendly_error_500_gemini() -> None:
    """HTTP 500 on Gemini produces an unavailable message."""
    provider = FailingProvider("HTTP 500: Internal Server Error")
    provider.name = "gemini"
    result = handle_request(
        _make_request(),
        provider,
        model="gemini-2.0-flash",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert "unavailable" in result.error.lower()
    assert "try again" in result.error.lower()


def test_api_key_never_in_error_message() -> None:
    """API key must never appear in error messages."""
    secret_key = "sk-secret-abc123xyz"
    provider = FailingProvider(f"HTTP 401: Unauthorized (key={secret_key})")
    provider.name = "openai"
    result = handle_request(
        _make_request(),
        provider,
        model="gpt-4o-mini",
        temperature=0.3,
        timeout=10.0,
    )
    assert result.success is False
    assert secret_key not in result.error
