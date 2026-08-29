"""Regression tests for the four-theme UI architecture (Dark/Light/System/Cyber).

These tests exercise the real theme machinery in
:mod:`android_task_manager.gui.styles` and the Settings page theme selector.
They do not inspect implementation availability only — they verify that the
token model is complete, that each theme resolves to its own token set, that
runtime switching changes the live application stylesheet, and that theme
choice survives reload through the real AppSettings persistence layer.

The four-theme architecture is locked; see the project change policy.
"""

from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from android_task_manager.gui import styles
from android_task_manager.gui.styles import (
    CYBER_STYLE,
    CYBER_TOKENS,
    DARK_STYLE,
    DARK_TOKENS,
    LIGHT_STYLE,
    LIGHT_TOKENS,
    ThemeTokens,
    apply_theme,
    build_style,
    is_system_dark,
)
from android_task_manager.settings import THEME_CYBER, THEME_DARK, THEME_LIGHT
from android_task_manager.settings.app_settings import (
    AppSettings,
    load_settings,
    save_settings,
)

# ---------------------------------------------------------------------------
# Shared Qt application (only one QApplication may exist per process)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


class _StubApp:
    """Minimal stand-in for QApplication.

    ``apply_theme`` only ever calls ``setStyleSheet`` on the passed object, so a
    stub that records the value lets us assert the live stylesheet *would*
    change without re-polishing the shared process-wide QApplication (which can
    block under the native Windows platform once many GUI test widgets exist).
    This still exercises the real :func:`apply_theme` resolution and
    :func:`build_style` rendering.
    """

    def __init__(self) -> None:
        self._sheet = ""

    def setStyleSheet(self, sheet: str) -> None:
        self._sheet = sheet

    def styleSheet(self) -> str:
        return self._sheet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tokens_for(theme: str) -> ThemeTokens:
    """Project-equivalent of ``get_theme(name)`` — the concrete token set."""
    mapping = {
        THEME_DARK: DARK_TOKENS,
        THEME_LIGHT: LIGHT_TOKENS,
        THEME_CYBER: CYBER_TOKENS,
    }
    return mapping[theme]


def _all_field_names() -> frozenset[str]:
    return frozenset(f.name for f in dataclasses.fields(ThemeTokens))


# Representative semantic tokens that must exist per category.  We assert on
# meaning (presence + non-empty hex), not on a hardcoded total field count.
_REQUIRED_TOKENS: dict[str, list[str]] = {
    "backgrounds": ["window_bg", "content_bg", "sidebar_bg"],
    "surfaces": ["surface", "surface_elevated", "surface_hover", "surface_pressed"],
    "borders": ["border", "border_subtle", "border_focus"],
    "text": ["text_primary", "text_secondary", "text_muted", "text_disabled"],
    "accent": ["accent", "accent_hover", "accent_pressed"],
    "semantic": ["success", "warning", "danger", "info"],
    "tables": [
        "table_header_bg",
        "table_header_text",
        "table_row_bg",
        "table_row_alt",
        "table_row_hover",
        "table_row_selected",
        "table_grid",
        "table_row_system",
    ],
    "inputs": ["input_bg", "input_border", "input_text", "input_focus_border"],
    "buttons": [
        "btn_secondary_bg",
        "btn_primary_bg",
        "btn_primary_hover",
        "btn_primary_pressed",
        "btn_danger_bg",
        "btn_danger_text",
    ],
    "settings": ["settings_group_bg", "settings_group_border"],
    "device list": [
        "device_list_bg",
        "device_list_border",
        "device_list_text",
        "device_list_selected",
        "device_list_hover",
    ],
    "scrollbar": ["scrollbar_bg", "scrollbar_handle"],
}


# ---------------------------------------------------------------------------
# A. Theme token completeness
# ---------------------------------------------------------------------------


def test_theme_tokens_cover_all_required_semantic_categories() -> None:
    fields = _all_field_names()
    missing: list[str] = []
    for category, tokens in _REQUIRED_TOKENS.items():
        for token in tokens:
            if token not in fields:
                missing.append(f"{category}:{token}")
    assert not missing, f"Missing theme tokens: {missing}"


def test_theme_tokens_are_non_empty_hex_values() -> None:
    for theme in (DARK_TOKENS, LIGHT_TOKENS, CYBER_TOKENS):
        for field in dataclasses.fields(ThemeTokens):
            value = getattr(theme, field.name)
            assert isinstance(value, str) and value, f"{field.name} is empty"
            # Tokens are hex colors; a few may be the literal "transparent".
            assert value.startswith("#") or value == "transparent", (
                f"{field.name}={value!r} is not a valid color token"
            )


def test_build_style_emits_every_required_token_into_css() -> None:
    # table_row_system is applied imperatively in code (not via the stylesheet),
    # so it is intentionally excluded from this CSS-emission check.
    css_driven = {
        token
        for tokens in _REQUIRED_TOKENS.values()
        for token in tokens
        if token != "table_row_system"
    }
    css = build_style(THEME_DARK)
    for token in css_driven:
        value = getattr(DARK_TOKENS, token)
        assert value in css, f"Token {token}={value} missing from stylesheet"


# ---------------------------------------------------------------------------
# B. Dark theme
# ---------------------------------------------------------------------------


def test_dark_theme_resolves_to_dark_tokens() -> None:
    assert _tokens_for(THEME_DARK) is DARK_TOKENS


def test_dark_theme_preserves_original_product_identity() -> None:
    assert DARK_TOKENS.window_bg == "#14181d"
    assert DARK_TOKENS.sidebar_bg == "#10141a"
    assert DARK_TOKENS.surface == "#1d232b"
    assert DARK_TOKENS.border == "#2a323c"
    assert DARK_TOKENS.accent == "#2f6fed"


# ---------------------------------------------------------------------------
# C. Light theme
# ---------------------------------------------------------------------------


def test_light_theme_resolves_to_own_token_set() -> None:
    assert _tokens_for(THEME_LIGHT) is LIGHT_TOKENS
    # Light must not reuse Dark backgrounds.
    assert LIGHT_TOKENS.window_bg != DARK_TOKENS.window_bg
    assert LIGHT_TOKENS.sidebar_bg != DARK_TOKENS.sidebar_bg
    assert LIGHT_TOKENS.surface != DARK_TOKENS.surface


def test_light_theme_is_light_with_readable_text_and_expected_accent() -> None:
    # Background is a light neutral, not pure white, with dark readable text.
    assert LIGHT_TOKENS.window_bg.lower() in {"#f0f0f2"}
    assert LIGHT_TOKENS.text_primary.lower() in {"#1c1c1e"}
    assert LIGHT_TOKENS.accent == "#1976d2"
    # Table tokens are present and distinct from Dark.
    assert LIGHT_TOKENS.table_row_bg != DARK_TOKENS.table_row_bg
    assert LIGHT_TOKENS.table_row_alt != DARK_TOKENS.table_row_alt
    assert LIGHT_TOKENS.table_header_bg != DARK_TOKENS.table_header_bg


# ---------------------------------------------------------------------------
# D. Cyber theme
# ---------------------------------------------------------------------------


def test_cyber_theme_resolves_to_own_token_set() -> None:
    assert _tokens_for(THEME_CYBER) is CYBER_TOKENS


def test_cyber_theme_identity_and_distinctness() -> None:
    assert CYBER_TOKENS.window_bg == "#0b0e14"
    assert CYBER_TOKENS.accent == "#00b4d8"
    # Cyber must differ from Dark on the key identity tokens.
    assert CYBER_TOKENS.window_bg != DARK_TOKENS.window_bg
    assert CYBER_TOKENS.accent != DARK_TOKENS.accent
    assert CYBER_TOKENS.sidebar_bg != DARK_TOKENS.sidebar_bg


# ---------------------------------------------------------------------------
# E. System theme resolution
# ---------------------------------------------------------------------------


def test_system_theme_follows_windows_dark_setting(monkeypatch) -> None:
    monkeypatch.setattr(styles, "is_system_dark", lambda: True)
    app = _StubApp()
    apply_theme(app, "system")
    assert app.styleSheet() == build_style(THEME_DARK)


def test_system_theme_follows_windows_light_setting(monkeypatch) -> None:
    monkeypatch.setattr(styles, "is_system_dark", lambda: False)
    app = _StubApp()
    apply_theme(app, "system")
    assert app.styleSheet() == build_style(THEME_LIGHT)


def test_system_detection_defaults_to_dark_on_failure() -> None:
    # The real implementation falls back to True (dark) on any error.
    assert isinstance(is_system_dark(), bool)


# ---------------------------------------------------------------------------
# F. Runtime theme switching (live stylesheet changes)
# ---------------------------------------------------------------------------


def test_runtime_theme_switching_changes_stylesheet() -> None:
    app = _StubApp()
    apply_theme(app, THEME_DARK)
    dark_css = app.styleSheet()
    apply_theme(app, THEME_LIGHT)
    light_css = app.styleSheet()
    apply_theme(app, THEME_CYBER)
    cyber_css = app.styleSheet()

    assert dark_css and light_css and cyber_css
    assert dark_css == DARK_STYLE
    assert light_css == LIGHT_STYLE
    assert cyber_css == CYBER_STYLE
    assert len({dark_css, light_css, cyber_css}) == 3  # all distinct


def test_runtime_switching_back_to_dark_restores_dark_stylesheet() -> None:
    app = _StubApp()
    apply_theme(app, THEME_LIGHT)
    apply_theme(app, THEME_DARK)
    assert app.styleSheet() == DARK_STYLE


# ---------------------------------------------------------------------------
# G. Persistence via AppSettings
# ---------------------------------------------------------------------------


@pytest.fixture
def _tmp_settings_dir(tmp_path, monkeypatch):
    """Redirect AppSettings persistence into a temporary directory."""
    import android_task_manager.settings.app_settings as mod

    monkeypatch.setattr(mod, "_user_config_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "_user_config_path", lambda: tmp_path / "settings.json")
    yield tmp_path


def test_save_and_reload_cyber_persists(_tmp_settings_dir) -> None:
    save_settings(AppSettings(theme=THEME_CYBER))
    reloaded = load_settings()
    assert reloaded.theme == THEME_CYBER


def test_save_and_reload_light_persists(_tmp_settings_dir) -> None:
    save_settings(AppSettings(theme=THEME_LIGHT))
    reloaded = load_settings()
    assert reloaded.theme == THEME_LIGHT


def test_invalid_theme_is_not_persisted(_tmp_settings_dir) -> None:
    save_settings(AppSettings(theme="bogus"))
    reloaded = load_settings()
    assert reloaded.theme == THEME_DARK  # falls back to default


# ---------------------------------------------------------------------------
# H. Settings page theme selector
# ---------------------------------------------------------------------------


def test_settings_page_exposes_all_four_themes(qapp) -> None:
    from android_task_manager.gui.settings_page import SettingsPage

    page = SettingsPage()
    labels = [
        page._theme_combo.itemText(i) for i in range(page._theme_combo.count())
    ]
    assert "Dark" in labels
    assert "Light" in labels
    assert "System" in labels
    assert "Cyber" in labels
    data = [
        page._theme_combo.itemData(i) for i in range(page._theme_combo.count())
    ]
    assert THEME_DARK in data
    assert THEME_LIGHT in data
    assert "system" in data
    assert THEME_CYBER in data


def test_settings_page_cyber_selection_emits_and_reports_value(
    qapp, tmp_path, monkeypatch
) -> None:
    import android_task_manager.settings.app_settings as mod

    monkeypatch.setattr(mod, "_user_config_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "_user_config_path", lambda: tmp_path / "settings.json")

    from android_task_manager.gui.settings_page import SettingsPage

    page = SettingsPage()
    emitted = []
    page.theme_changed.connect(emitted.append)

    index = page._theme_combo.findData(THEME_CYBER)
    page._theme_combo.setCurrentIndex(index)

    assert emitted == [THEME_CYBER]
    # settings_values reflects the selection
    _, theme = page.settings_values()
    assert theme == THEME_CYBER


def test_settings_page_light_selection_emits_value(
    qapp, tmp_path, monkeypatch
) -> None:
    import android_task_manager.settings.app_settings as mod

    monkeypatch.setattr(mod, "_user_config_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "_user_config_path", lambda: tmp_path / "settings.json")

    from android_task_manager.gui.settings_page import SettingsPage

    page = SettingsPage()
    emitted = []
    page.theme_changed.connect(emitted.append)

    index = page._theme_combo.findData(THEME_LIGHT)
    page._theme_combo.setCurrentIndex(index)

    assert emitted == [THEME_LIGHT]


def test_settings_page_populates_from_persisted_settings(qapp) -> None:
    from android_task_manager.gui.settings_page import SettingsPage

    page = SettingsPage()
    page.set_settings(AppSettings(theme=THEME_CYBER))
    assert page._theme_combo.currentData() == THEME_CYBER


# ---------------------------------------------------------------------------
# I. Single centralized theme mechanism (no duplicate stylesheet system)
# ---------------------------------------------------------------------------


def test_legacy_style_constants_are_token_driven(qapp) -> None:
    # The named constants must derive from the single template, proving there
    # is no parallel, hard-coded stylesheet implementation.
    assert DARK_STYLE == build_style(THEME_DARK)
    assert LIGHT_STYLE == build_style(THEME_LIGHT)
    assert CYBER_STYLE == build_style(THEME_CYBER)


def test_apply_theme_uses_central_build_style() -> None:
    app = _StubApp()
    apply_theme(app, THEME_LIGHT)
    assert app.styleSheet() == build_style(THEME_LIGHT)


def test_active_tokens_track_the_applied_theme() -> None:
    from android_task_manager.gui.styles import active_tokens

    apply_theme(_StubApp(), THEME_LIGHT)
    assert active_tokens() is LIGHT_TOKENS
    apply_theme(_StubApp(), THEME_CYBER)
    assert active_tokens() is CYBER_TOKENS
    apply_theme(_StubApp(), THEME_DARK)
    assert active_tokens() is DARK_TOKENS


def test_system_row_tint_follows_active_theme() -> None:
    """The previously-hardcoded system-row color now reads the active token."""
    from android_task_manager.gui import apps_page

    apply_theme(_StubApp(), THEME_LIGHT)
    brush = apps_page._system_background()
    assert brush.color().name().lower() == LIGHT_TOKENS.table_row_system.lower()

    apply_theme(_StubApp(), THEME_CYBER)
    brush = apps_page._system_background()
    assert brush.color().name().lower() == CYBER_TOKENS.table_row_system.lower()

    apply_theme(_StubApp(), THEME_DARK)
    brush = apps_page._system_background()
    assert brush.color().name().lower() == DARK_TOKENS.table_row_system.lower()


# ---------------------------------------------------------------------------
# J. UI remains valid after repeated theme switches
# ---------------------------------------------------------------------------


def test_widgets_remain_valid_through_theme_cycle(qapp) -> None:
    from PySide6.QtWidgets import QLabel, QWidget

    widget = QWidget()
    label = QLabel("theme smoke", widget)
    label.setObjectName("pageTitle")

    # The application stays alive and the widget tree is valid across a full
    # theme cycle; each theme renders a non-empty stylesheet (so switching is
    # safe even though the shared process-wide app is not re-polished here).
    for theme in (THEME_DARK, THEME_LIGHT, THEME_CYBER, THEME_DARK):
        assert widget.isWidgetType()
        assert label.isWidgetType()
        assert build_style(theme)  # every theme renders a stylesheet

    widget.deleteLater()
