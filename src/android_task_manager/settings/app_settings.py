"""Application-level user settings for the Android Task Manager shell.

This is the first general (non-Copilot) settings store in the application.
It follows the exact persistence conventions established by the Copilot
config module (:mod:`android_task_manager.copilot.settings`): a dataclass, a
``load_*``/``save_*`` pair, JSON in the platform user-data directory, and
atomic tmp+fsync+os.replace writes.

The settings store holds application-wide preferences: theme, monitoring
interval, and Copilot UI preferences. Nothing in this module touches ADB,
collectors, or the GUI — it is pure, testable persistence.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("android_task_manager.settings")

#: Filename for the app-shell settings JSON.
SETTINGS_FILENAME = "settings.json"

#: Theme constants.
THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_SYSTEM = "system"
THEME_CYBER = "cyber"
DEFAULT_THEME = THEME_DARK

#: Defaults for monitoring-tied settings.
DEFAULT_REFRESH_INTERVAL_S = 3
DEFAULT_COPILOT_CONTEXT_IN_UI = True


@dataclass
class AppSettings:
    """User interface / shell settings across the whole application."""

    #: Theme: dark (default), light, or system.
    theme: str = DEFAULT_THEME
    #: Monitoring refresh interval in seconds.
    refresh_interval_s: int = DEFAULT_REFRESH_INTERVAL_S
    #: Show live CPU/RAM/battery context in the Copilot indicator.
    copilot_context_in_ui: bool = DEFAULT_COPILOT_CONTEXT_IN_UI


def _user_config_path() -> Path | None:
    """Path to the settings JSON, or None when the platform dir is unknown."""
    try:
        from ..baseline.storage import user_data_dir

        return user_data_dir() / SETTINGS_FILENAME
    except (ImportError, RuntimeError):
        return None


def _user_config_dir() -> Path | None:
    try:
        from ..baseline.storage import user_data_dir

        return user_data_dir()
    except (ImportError, RuntimeError):
        return None


def load_settings() -> AppSettings:
    """Load the app-shell settings; return defaults on any failure."""
    settings = AppSettings()
    path = _user_config_path()
    if path is None:
        return settings
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return settings
    if "theme" in data:
        value = str(data["theme"])
        if value in (THEME_DARK, THEME_LIGHT, THEME_SYSTEM, THEME_CYBER):
            settings.theme = value
    if "refresh_interval_s" in data:
        try:
            settings.refresh_interval_s = int(data["refresh_interval_s"])
        except (TypeError, ValueError):
            pass
    if "copilot_context_in_ui" in data:
        settings.copilot_context_in_ui = bool(data["copilot_context_in_ui"])
    return settings


def save_settings(settings: AppSettings) -> None:
    """Atomic write of the app-shell settings to the user-data directory."""
    directory = _user_config_dir()
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SETTINGS_FILENAME
    data = {
        "theme": settings.theme,
        "refresh_interval_s": settings.refresh_interval_s,
        "copilot_context_in_ui": settings.copilot_context_in_ui,
    }
    text = json.dumps(data, indent=2, sort_keys=True)
    temp = path.with_name(f"{path.name}.tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


__all__ = [
    "AppSettings",
    "DEFAULT_COPILOT_CONTEXT_IN_UI",
    "DEFAULT_REFRESH_INTERVAL_S",
    "DEFAULT_THEME",
    "SETTINGS_FILENAME",
    "THEME_DARK",
    "THEME_LIGHT",
    "THEME_SYSTEM",
    "load_settings",
    "save_settings",
]
