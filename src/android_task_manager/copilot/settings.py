"""Copilot configuration — user-owned API key stored locally.

Users configure their own Gemini API key through the Copilot Settings UI.
The key is stored in copilot-config.json in the platform user-data directory.
No build-time or environment-based key injection is used.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("android_task_manager.copilot")

CONFIG_FILENAME = "copilot-config.json"

_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com"
_DEFAULT_MODEL = "gemini-2.0-flash"


@dataclass
class CopilotConfig:
    """Copilot settings — user-provided Gemini API key."""

    enabled: bool = True
    provider: str = "gemini"
    model: str = _DEFAULT_MODEL
    endpoint: str = _GEMINI_ENDPOINT
    api_key: str = ""
    temperature: float = 0.3
    timeout: float = 30.0
    max_history: int = 10

    @property
    def is_configured(self) -> bool:
        """True when a valid API key is available for the configured provider."""
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def masked_api_key(self) -> str:
        """Return a masked representation of the API key for display."""
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return "*" * (len(self.api_key) - 4) + self.api_key[-4:]


def load_config() -> CopilotConfig:
    """Load config from user_data_dir(); return defaults on any failure."""
    config = CopilotConfig()
    path = _user_config_path()
    if path is None:
        return _apply_env_fallback(config)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return _apply_env_fallback(config)
    if "provider" in data:
        config.provider = str(data["provider"])
    if "model" in data:
        config.model = str(data["model"])
    if "endpoint" in data:
        config.endpoint = str(data["endpoint"])
    if "api_key" in data:
        config.api_key = str(data["api_key"])
    if "temperature" in data:
        config.temperature = float(data["temperature"])
    if "timeout" in data:
        config.timeout = float(data["timeout"])
    if "max_history" in data:
        config.max_history = int(data["max_history"])
    if "enabled" in data:
        config.enabled = bool(data["enabled"])
    return _apply_env_fallback(config)


def save_config(config: CopilotConfig) -> None:
    """Atomic write to user_data_dir()."""
    directory = _user_config_dir()
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CONFIG_FILENAME
    data = {
        "enabled": config.enabled,
        "provider": config.provider,
        "model": config.model,
        "endpoint": config.endpoint,
        "api_key": config.api_key,
        "temperature": config.temperature,
        "timeout": config.timeout,
        "max_history": config.max_history,
    }
    text = json.dumps(data, indent=2, sort_keys=True)
    temp = path.with_name(f"{path.name}.tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _apply_env_fallback(config: CopilotConfig) -> CopilotConfig:
    """Optional dev/test fallback — not required for normal users."""
    env_key = os.environ.get("ANDROID_TASK_MANAGER_GEMINI_API_KEY", "")
    if env_key and not config.api_key:
        config.api_key = env_key
    return config


def _user_config_path() -> Path | None:
    try:
        from ..baseline.storage import user_data_dir

        return user_data_dir() / CONFIG_FILENAME
    except (ImportError, RuntimeError):
        return None


def _user_config_dir() -> Path | None:
    try:
        from ..baseline.storage import user_data_dir

        return user_data_dir()
    except (ImportError, RuntimeError):
        return None
