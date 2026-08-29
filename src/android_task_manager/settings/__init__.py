"""Application-level shell settings (theme, monitoring, privacy)."""

from .app_settings import (
    DEFAULT_COPILOT_CONTEXT_IN_UI,
    DEFAULT_REFRESH_INTERVAL_S,
    DEFAULT_THEME,
    THEME_CYBER,
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    AppSettings,
    load_settings,
    save_settings,
)

__all__ = [
    "AppSettings",
    "DEFAULT_COPILOT_CONTEXT_IN_UI",
    "DEFAULT_REFRESH_INTERVAL_S",
    "DEFAULT_THEME",
    "THEME_CYBER",
    "THEME_DARK",
    "THEME_LIGHT",
    "THEME_SYSTEM",
    "load_settings",
    "save_settings",
]
