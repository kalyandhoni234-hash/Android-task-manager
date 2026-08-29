"""Tests for the Copilot prompt builder and response parser."""

from __future__ import annotations

import time

from android_task_manager.copilot.models import CopilotContext, CopilotMessage, CopilotRole
from android_task_manager.copilot.prompts import build_messages, parse_response


def _ctx(**overrides: object) -> CopilotContext:
    defaults: dict[str, object] = {
        "current_page": "overview",
        "connected": True,
        "device_label": "Pixel 7",
        "android_version": "14",
        "cpu_percent": 45.0,
        "memory_used_percent": 60.0,
        "memory_total_kb": 4_000_000,
    }
    defaults.update(overrides)
    return CopilotContext(**defaults)  # type: ignore[arg-type]


def test_build_messages_structure() -> None:
    ctx = _ctx()
    msgs = build_messages("What is RAM?", ctx)
    assert len(msgs) >= 3
    assert msgs[0]["role"] == "system"
    assert "Android Task Manager" in msgs[0]["content"]
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "What is RAM?"


def test_build_messages_includes_context() -> None:
    ctx = _ctx(cpu_percent=75.0)
    msgs = build_messages("test", ctx)
    context_content = " ".join(m["content"] for m in msgs if m["role"] == "system")
    assert "75.0%" in context_content
    assert "Pixel 7" in context_content


def test_build_messages_page_emphasis() -> None:
    ctx = _ctx(current_page="processes")
    msgs = build_messages("test", ctx)
    page_msg = msgs[1]["content"]
    assert "process" in page_msg.lower()


def test_build_messages_with_history() -> None:
    ctx = _ctx()
    history = (
        CopilotMessage(
            role=CopilotRole.USER,
            content="What is CPU?",
            timestamp=time.time(),
        ),
        CopilotMessage(
            role=CopilotRole.ASSISTANT,
            content="CPU is the processor.",
            timestamp=time.time(),
        ),
    )
    msgs = build_messages("Follow up", ctx, history)
    assert len(msgs) >= 5
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles


def test_parse_response_simple() -> None:
    raw = "Your CPU is at 45% which is normal."
    answer, suggestions, confidence, pages = parse_response(raw)
    assert answer == "Your CPU is at 45% which is normal."
    assert suggestions == ()
    assert confidence == "medium"
    assert pages == ()


def test_parse_response_full() -> None:
    raw = (
        "CPU usage is elevated.\n"
        "\n"
        "Suggestions:\n"
        "- Check com.example.app\n"
        "- Review background processes\n"
        "\n"
        "Confidence: high\n"
        "See also: processes, health\n"
    )
    answer, suggestions, confidence, pages = parse_response(raw)
    assert "CPU usage is elevated" in answer
    assert len(suggestions) == 2
    assert "Check com.example.app" in suggestions[0]
    assert confidence == "high"
    assert pages == ("processes", "health")


def test_parse_response_low_confidence() -> None:
    raw = "I'm not sure.\n\nConfidence: low\n"
    answer, suggestions, confidence, pages = parse_response(raw)
    assert confidence == "low"


def test_parse_response_empty() -> None:
    answer, suggestions, confidence, pages = parse_response("")
    assert answer == ""
    assert confidence == "medium"
