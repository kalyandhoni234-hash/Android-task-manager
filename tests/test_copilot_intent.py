"""Tests for the deterministic Copilot intent classifier."""

from __future__ import annotations

from android_task_manager.copilot.intent import (
    INTENT_BATTERY,
    INTENT_CLOSE_APP,
    INTENT_CPU,
    INTENT_DIAGNOSTIC,
    INTENT_GAMING,
    INTENT_GENERAL,
    INTENT_HEALTH,
    INTENT_MEMORY,
    INTENT_NETWORK,
    INTENT_OVERHEAT,
    INTENT_PERFORMANCE,
    INTENT_SLOW,
    INTENT_STORAGE,
    INTENT_WHAT_WRONG,
    classify_intent,
)


def test_gaming_intent() -> None:
    assert classify_intent("I want to play Zooba. What should I close?") == INTENT_GAMING
    assert classify_intent("I need maximum RAM for a game.") == INTENT_GAMING
    assert classify_intent("Optimize for gaming") == INTENT_GAMING


def test_close_app_intent() -> None:
    assert classify_intent("What should I close?") == INTENT_CLOSE_APP
    assert classify_intent("Which app can I safely stop?") == INTENT_CLOSE_APP
    assert classify_intent("Should I close Chrome?") == INTENT_CLOSE_APP


def test_slow_intent() -> None:
    assert classify_intent("Why is my phone slow?") == INTENT_SLOW
    assert classify_intent("My phone is lagging") == INTENT_SLOW
    assert classify_intent("the device is stuttering") == INTENT_SLOW


def test_battery_intent() -> None:
    assert classify_intent("Why is my battery draining?") == INTENT_BATTERY
    assert classify_intent("My battery is draining") == INTENT_BATTERY


def test_cpu_intent() -> None:
    assert classify_intent("Why is CPU usage so high?") == INTENT_CPU
    assert classify_intent("CPU utilization") == INTENT_CPU


def test_memory_intent() -> None:
    assert classify_intent("Which apps are consuming RAM?") == INTENT_MEMORY
    assert classify_intent("What's using my memory?") == INTENT_MEMORY


def test_storage_intent() -> None:
    assert classify_intent("Why is storage almost full?") == INTENT_STORAGE
    assert classify_intent("storage full") == INTENT_STORAGE


def test_overheat_intent() -> None:
    assert classify_intent("Why is my phone overheating?") == INTENT_OVERHEAT
    assert classify_intent("device is hot") == INTENT_OVERHEAT


def test_health_intent() -> None:
    assert classify_intent("Explain my health score.") == INTENT_HEALTH
    assert classify_intent("How is my phone health?") == INTENT_HEALTH


def test_diagnostic_intent() -> None:
    assert classify_intent("Explain this diagnostic.") == INTENT_DIAGNOSTIC
    assert classify_intent("What triggered this finding?") == INTENT_DIAGNOSTIC


def test_performance_intent() -> None:
    assert classify_intent("Why did performance drop?") == INTENT_PERFORMANCE
    assert classify_intent("performance is bad") == INTENT_PERFORMANCE


def test_network_intent() -> None:
    assert classify_intent("What's happening with my network?") == INTENT_NETWORK
    assert classify_intent("my wifi is slow") == INTENT_NETWORK


def test_what_wrong_intent() -> None:
    assert classify_intent("What is wrong with my phone?") == INTENT_WHAT_WRONG
    assert classify_intent("Is my phone ok?") == INTENT_WHAT_WRONG
    assert classify_intent("Is my device okay?") == INTENT_WHAT_WRONG
    assert classify_intent("Is something wrong with my phone?") == INTENT_WHAT_WRONG
    assert classify_intent("What's wrong with my phone?") == INTENT_WHAT_WRONG
    assert classify_intent("Is there anything wrong?") == INTENT_WHAT_WRONG
    assert classify_intent("Does my phone have any problems?") == INTENT_WHAT_WRONG
    assert classify_intent("How is my phone doing?") == INTENT_WHAT_WRONG
    assert classify_intent("Is my phone healthy?") == INTENT_WHAT_WRONG


def test_what_wrong_not_oversharing() -> None:
    assert classify_intent("What's using my RAM?") != INTENT_WHAT_WRONG
    assert classify_intent("Why is my phone slow?") != INTENT_WHAT_WRONG
    assert classify_intent("What apps are running?") != INTENT_WHAT_WRONG
    assert classify_intent("How much battery do I have?") != INTENT_WHAT_WRONG
    assert classify_intent("Show me my network") != INTENT_WHAT_WRONG
    assert classify_intent("Prepare my phone for gaming") != INTENT_WHAT_WRONG


def test_specific_subsystem_beats_what_wrong() -> None:
    assert classify_intent("Is my battery having problems?") == INTENT_BATTERY
    assert classify_intent("Is my wifi having issues?") == INTENT_NETWORK
    assert classify_intent("My storage is full") == INTENT_STORAGE
    assert classify_intent("My RAM is low") == INTENT_MEMORY
    assert classify_intent("Why is my CPU so high?") == INTENT_CPU


def test_general_fallback() -> None:
    assert classify_intent("hello there") == INTENT_GENERAL
    assert classify_intent("") == INTENT_GENERAL
