"""Tests for the Copilot LLM providers."""

from __future__ import annotations

import json
from email.message import Message
from unittest.mock import MagicMock, patch

from android_task_manager.copilot.providers import (
    LLMProviderError,
    OllamaProvider,
    OpenAIProvider,
)


class TestOpenAIProvider:
    def test_name(self) -> None:
        p = OpenAIProvider(endpoint="https://api.openai.com", api_key="sk-test")
        assert p.name == "openai"

    @patch("android_task_manager.copilot.providers.urllib.request.urlopen")
    def test_chat_success(self, mock_urlopen: MagicMock) -> None:
        response_body = json.dumps({
            "choices": [{"message": {"content": "Hello!"}}],
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        p = OpenAIProvider(endpoint="https://api.openai.com", api_key="sk-test")
        result = p.chat(
            [{"role": "user", "content": "Hi"}],
            model="gpt-4o-mini",
            temperature=0.3,
            timeout=10.0,
        )
        assert result == "Hello!"

    @patch("android_task_manager.copilot.providers.urllib.request.urlopen")
    def test_chat_http_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=429, msg="Too Many Requests", hdrs=Message(), fp=None
        )
        p = OpenAIProvider(endpoint="https://api.openai.com", api_key="sk-test")
        try:
            p.chat(
                [{"role": "user", "content": "Hi"}],
                model="gpt-4o-mini",
                temperature=0.3,
                timeout=10.0,
            )
        except LLMProviderError as exc:
            assert "429" in str(exc)
            assert exc.retryable is True
        else:
            raise AssertionError("Should have raised LLMProviderError")

    @patch("android_task_manager.copilot.providers.urllib.request.urlopen")
    def test_chat_malformed_response(self, mock_urlopen: MagicMock) -> None:
        response_body = json.dumps({"unexpected": "format"}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        p = OpenAIProvider(endpoint="https://api.openai.com", api_key="sk-test")
        try:
            p.chat(
                [{"role": "user", "content": "Hi"}],
                model="gpt-4o-mini",
                temperature=0.3,
                timeout=10.0,
            )
        except LLMProviderError as exc:
            assert "Malformed" in str(exc)
        else:
            raise AssertionError("Should have raised LLMProviderError")


class TestOllamaProvider:
    def test_name(self) -> None:
        p = OllamaProvider(endpoint="http://localhost:11434")
        assert p.name == "ollama"

    @patch("android_task_manager.copilot.providers.urllib.request.urlopen")
    def test_chat_success(self, mock_urlopen: MagicMock) -> None:
        response_body = json.dumps({
            "message": {"content": "Ollama response"},
        }).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        p = OllamaProvider(endpoint="http://localhost:11434")
        result = p.chat(
            [{"role": "user", "content": "Hi"}],
            model="llama3",
            temperature=0.3,
            timeout=10.0,
        )
        assert result == "Ollama response"

    @patch("android_task_manager.copilot.providers.urllib.request.urlopen")
    def test_chat_malformed_response(self, mock_urlopen: MagicMock) -> None:
        response_body = json.dumps({"unexpected": "format"}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        p = OllamaProvider(endpoint="http://localhost:11434")
        try:
            p.chat(
                [{"role": "user", "content": "Hi"}],
                model="llama3",
                temperature=0.3,
                timeout=10.0,
            )
        except LLMProviderError as exc:
            assert "Malformed" in str(exc)
        else:
            raise AssertionError("Should have raised LLMProviderError")
