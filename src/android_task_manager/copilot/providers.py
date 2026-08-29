"""LLM provider abstraction — stdlib HTTP only, zero new dependencies.

Provider implementations for Gemini, OpenAI-compatible APIs, and Ollama.
The core application never cares which model backend is used.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol

logger = logging.getLogger("android_task_manager.copilot")


class LLMProviderError(Exception):
    """Typed failure from any provider."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    """Abstract interface for LLM backends."""

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        timeout: float,
    ) -> str: ...

    @property
    def name(self) -> str: ...


class GeminiProvider:
    """Google Gemini REST API (generateContent endpoint).

    API key is passed as a URL query parameter per Google's convention.
    System instructions use the ``systemInstruction`` field.
    User/assistant history uses ``contents`` with role ``user``/``model``.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://generativelanguage.googleapis.com",
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")

    @property
    def name(self) -> str:
        return "gemini"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        timeout: float,
    ) -> str:
        url = (
            f"{self._endpoint}/v1beta/models/{model}:generateContent"
            f"?key={self._api_key}"
        )

        system_parts: list[str] = []
        contents: list[dict[str, object]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            else:
                gemini_role = "model" if role == "assistant" else "user"
                if contents and contents[-1]["role"] == gemini_role:
                    existing = contents[-1]["parts"][0]["text"]  # type: ignore[index]
                    contents[-1]["parts"] = [{"text": f"{existing}\n{content}"}]  # type: ignore[index]
                else:
                    contents.append({"role": gemini_role, "parts": [{"text": content}]})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})

        payload: dict[str, object] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        payload["generationConfig"] = {"temperature": temperature}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 500, 502, 503)
            raise LLMProviderError(
                f"HTTP {exc.code}: {exc.reason}", retryable=retryable
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LLMProviderError(str(exc), retryable=True) from exc

        try:
            candidates = body["candidates"]
            return candidates[0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Malformed response from Gemini") from exc


class OpenAIProvider:
    """OpenAI-compatible REST API (OpenAI, OpenRouter, local servers)."""

    def __init__(self, endpoint: str, api_key: str | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "openai"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        timeout: float,
    ) -> str:
        url = f"{self._endpoint}/v1/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
        ).encode("utf-8")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        req = urllib.request.Request(
            url, data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retryable = exc.code in (429, 500, 502, 503)
            raise LLMProviderError(
                f"HTTP {exc.code}: {exc.reason}", retryable=retryable
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LLMProviderError(str(exc), retryable=True) from exc

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Malformed response from provider") from exc


class OllamaProvider:
    """Ollama local HTTP API (POST /api/chat)."""

    def __init__(self, endpoint: str = "http://localhost:11434") -> None:
        self._endpoint = endpoint.rstrip("/")

    @property
    def name(self) -> str:
        return "ollama"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        temperature: float,
        timeout: float,
    ) -> str:
        url = f"{self._endpoint}/api/chat"
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(
                f"HTTP {exc.code}: {exc.reason}",
                retryable=exc.code in (500, 502, 503),
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LLMProviderError(str(exc), retryable=True) from exc

        try:
            return body["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMProviderError("Malformed Ollama response") from exc


def build_provider(
    config_endpoint: str, config_api_key: str, provider_name: str
) -> LLMProvider:
    """Factory: create the appropriate provider from config."""
    if provider_name == "gemini":
        return GeminiProvider(
            api_key=config_api_key,
            endpoint=config_endpoint or "https://generativelanguage.googleapis.com",
        )
    if provider_name == "ollama":
        return OllamaProvider(endpoint=config_endpoint or "http://localhost:11434")
    return OpenAIProvider(
        endpoint=config_endpoint or "https://api.openai.com",
        api_key=config_api_key or None,
    )
