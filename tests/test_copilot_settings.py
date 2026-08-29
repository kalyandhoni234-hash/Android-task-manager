"""Tests for Copilot settings persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from android_task_manager.copilot.settings import CopilotConfig, load_config, save_config

_MOCK_TARGET = "android_task_manager.baseline.storage.user_data_dir"


def test_load_config_defaults(tmp_path: Path) -> None:
    with patch(_MOCK_TARGET, return_value=tmp_path / "nonexistent"):
        config = load_config()
    assert config.enabled is True
    assert config.provider == "gemini"
    assert "gemini" in config.model.lower()
    assert config.temperature == 0.3
    assert config.timeout == 30.0


def test_load_config_from_file(tmp_path: Path) -> None:
    data = {
        "enabled": True,
        "provider": "ollama",
        "model": "llama3",
        "endpoint": "http://localhost:11434",
        "api_key": "",
        "temperature": 0.5,
        "timeout": 60.0,
        "max_history": 5,
    }
    config_file = tmp_path / "copilot-config.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    with patch(_MOCK_TARGET, return_value=tmp_path):
        config = load_config()
    assert config.enabled is True
    assert config.provider == "ollama"
    assert config.model == "llama3"
    assert config.temperature == 0.5
    assert config.timeout == 60.0
    assert config.max_history == 5


def test_load_config_corrupt_file(tmp_path: Path) -> None:
    config_file = tmp_path / "copilot-config.json"
    config_file.write_text("not json {{{", encoding="utf-8")
    with patch(_MOCK_TARGET, return_value=tmp_path):
        config = load_config()
    assert config.enabled is True
    assert config.provider == "gemini"


def test_save_config(tmp_path: Path) -> None:
    config = CopilotConfig(
        enabled=True,
        provider="ollama",
        model="llama3",
        endpoint="http://localhost:11434",
        api_key="secret",
        temperature=0.7,
        timeout=45.0,
        max_history=8,
    )
    with patch(_MOCK_TARGET, return_value=tmp_path):
        save_config(config)
    config_file = tmp_path / "copilot-config.json"
    assert config_file.exists()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert data["enabled"] is True
    assert data["provider"] == "ollama"
    assert data["model"] == "llama3"
    assert data["api_key"] == "secret"
    assert data["temperature"] == 0.7


def test_save_config_atomic(tmp_path: Path) -> None:
    config = CopilotConfig(enabled=True)
    with patch(_MOCK_TARGET, return_value=tmp_path):
        save_config(config)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
