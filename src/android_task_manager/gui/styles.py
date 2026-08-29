"""Centralized theming for the Android Task Manager dashboard.

Four visual presentations: **Dark** (default), **Light**, **Cyber**, and
**System** (auto-resolves to Dark or Light based on the Windows appearance).

The architecture uses semantic colour tokens to decouple *what* a colour
means from its concrete hex value.  Each theme defines a complete token set;
a single :func:`build_style` function renders the CSS from those tokens.
This avoids duplicating the full stylesheet four times while keeping every
theme independently maintainable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

from PySide6.QtWidgets import QApplication, QWidget

# --------------------------------------------------------------------------- #
# Repolish helper
# --------------------------------------------------------------------------- #

def repolish(widget: QWidget) -> None:
    """Re-apply the app stylesheet to *widget* after an objectName change.

    Qt only evaluates an objectName-based stylesheet rule when a widget is
    polished; changing ``objectName`` at runtime without re-polishing leaves
    the old color/weight in place.  Widgets that swap objectNames to reflect
    state (connection, severity) must call this after every swap.
    """
    app = QApplication.instance()
    if app is not None and hasattr(app, "style"):
        app.style().unpolish(widget)
        app.style().polish(widget)


# --------------------------------------------------------------------------- #
# Semantic colour tokens
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ThemeTokens:
    """Semantic colour tokens for one visual theme."""

    # --- Backgrounds --------------------------------------------------------
    window_bg: str
    content_bg: str
    sidebar_bg: str

    # --- Surfaces -----------------------------------------------------------
    surface: str
    surface_elevated: str
    surface_hover: str
    surface_pressed: str

    # --- Borders ------------------------------------------------------------
    border: str
    border_subtle: str
    border_focus: str

    # --- Text ---------------------------------------------------------------
    text_primary: str
    text_secondary: str
    text_muted: str
    text_disabled: str

    # --- Accent -------------------------------------------------------------
    accent: str
    accent_hover: str
    accent_pressed: str

    # --- Semantic -----------------------------------------------------------
    success: str
    warning: str
    danger: str
    info: str

    # --- Tables -------------------------------------------------------------
    table_header_bg: str
    table_header_text: str
    table_row_bg: str
    table_row_alt: str
    table_row_hover: str
    table_row_selected: str
    table_grid: str
    #: Quiet tint for system-app rows so the destructive-control boundary
    #: reads at a glance; theme-aware (replaces a previously hardcoded color).
    table_row_system: str

    # --- Inputs -------------------------------------------------------------
    input_bg: str
    input_border: str
    input_text: str
    input_focus_border: str

    # --- Scrollbar ----------------------------------------------------------
    scrollbar_bg: str
    scrollbar_handle: str

    # --- Cards / Panels -----------------------------------------------------
    card_bg: str
    card_border: str
    panel_bg: str

    # --- Buttons (secondary) ------------------------------------------------
    btn_secondary_bg: str
    btn_secondary_text: str
    btn_secondary_border: str
    btn_secondary_hover: str

    # --- Buttons (primary) --------------------------------------------------
    btn_primary_bg: str
    btn_primary_text: str
    btn_primary_hover: str
    btn_primary_pressed: str
    btn_primary_disabled_bg: str
    btn_primary_disabled_text: str

    # --- Buttons (danger) ---------------------------------------------------
    btn_danger_bg: str
    btn_danger_text: str
    btn_danger_border: str
    btn_danger_hover: str
    btn_danger_pressed: str

    # --- Link button --------------------------------------------------------
    link_text: str
    link_hover: str
    link_pressed: str

    # --- Finding cards ------------------------------------------------------
    finding_bg: str
    finding_border: str
    finding_high_border: str
    finding_severity_bg: str

    # --- Perf badges --------------------------------------------------------
    perf_card_bg: str
    perf_metric_bg: str

    # --- Settings -----------------------------------------------------------
    settings_group_bg: str
    settings_group_border: str

    # --- Combo / Spin / Check -----------------------------------------------
    combo_bg: str
    combo_border: str
    combo_text: str
    combo_hover_border: str
    combo_arrow: str
    combo_select_bg: str

    spin_bg: str
    spin_border: str
    spin_text: str
    spin_hover_border: str
    spin_focus_border: str

    check_text: str
    check_border: str
    check_bg: str
    check_checked_bg: str
    check_checked_border: str
    check_hover_border: str

    # --- Device list --------------------------------------------------------
    device_list_bg: str
    device_list_border: str
    device_list_text: str
    device_list_selected: str
    device_list_hover: str


# --------------------------------------------------------------------------- #
# Concrete token sets
# --------------------------------------------------------------------------- #

DARK_TOKENS: Final[ThemeTokens] = ThemeTokens(
    # Backgrounds
    window_bg="#14181d",
    content_bg="#14181d",
    sidebar_bg="#10141a",

    # Surfaces
    surface="#1d232b",
    surface_elevated="#232b35",
    surface_hover="#242c36",
    surface_pressed="#1b2430",

    # Borders
    border="#2a323c",
    border_subtle="#232b35",
    border_focus="#3d9be9",

    # Text
    text_primary="#e8eef5",
    text_secondary="#d8dee6",
    text_muted="#7a8794",
    text_disabled="#5c6672",

    # Accent
    accent="#2f6fed",
    accent_hover="#3d7df5",
    accent_pressed="#2559c2",

    # Semantic
    success="#3ddc84",
    warning="#f5a524",
    danger="#ff5f56",
    info="#3d9be9",

    # Tables
    table_header_bg="#232b35",
    table_header_text="#7a8794",
    table_row_bg="#1d232b",
    table_row_alt="#202833",
    table_row_hover="#242c36",
    table_row_selected="#2b3a4d",
    table_grid="transparent",
    table_row_system="#2b3238",

    # Inputs
    input_bg="#1d232b",
    input_border="#2a323c",
    input_text="#d8dee6",
    input_focus_border="#3d9be9",

    # Scrollbar
    scrollbar_bg="#1d232b",
    scrollbar_handle="#3a4552",

    # Cards
    card_bg="#1d232b",
    card_border="#2a323c",
    panel_bg="#1d232b",

    # Secondary buttons
    btn_secondary_bg="#232b35",
    btn_secondary_text="#d8dee6",
    btn_secondary_border="#2a323c",
    btn_secondary_hover="#2b3541",

    # Primary buttons
    btn_primary_bg="#2f6fed",
    btn_primary_text="#ffffff",
    btn_primary_hover="#3d7df5",
    btn_primary_pressed="#2559c2",
    btn_primary_disabled_bg="#232b35",
    btn_primary_disabled_text="#5c6672",

    # Danger buttons
    btn_danger_bg="#1d232b",
    btn_danger_text="#ff5f56",
    btn_danger_border="#5a2a2a",
    btn_danger_hover="#2a1a1d",
    btn_danger_pressed="#5a2a2a",

    # Links
    link_text="#3d9be9",
    link_hover="#6db5f0",
    link_pressed="#2a7fc9",

    # Finding cards
    finding_bg="#1d232b",
    finding_border="#2a323c",
    finding_high_border="#4a2f33",
    finding_severity_bg="#232b35",

    # Perf
    perf_card_bg="#1a2027",
    perf_metric_bg="#1a2027",

    # Settings
    settings_group_bg="#1d232b",
    settings_group_border="#2a323c",

    # Combo
    combo_bg="#1d232b",
    combo_border="#2a323c",
    combo_text="#d8dee6",
    combo_hover_border="#3a4552",
    combo_arrow="#7a8794",
    combo_select_bg="#2b3a4d",

    # Spin
    spin_bg="#1d232b",
    spin_border="#2a323c",
    spin_text="#d8dee6",
    spin_hover_border="#3a4552",
    spin_focus_border="#3d9be9",

    # Check
    check_text="#d8dee6",
    check_border="#3a4552",
    check_bg="#1d232b",
    check_checked_bg="#2f6fed",
    check_checked_border="#2f6fed",
    check_hover_border="#3d9be9",

    # Device list
    device_list_bg="#1d232b",
    device_list_border="#2a323c",
    device_list_text="#d8dee6",
    device_list_selected="#2b3a4d",
    device_list_hover="#232b35",
)

LIGHT_TOKENS: Final[ThemeTokens] = ThemeTokens(
    # Backgrounds — warm neutral grays, not pure white
    window_bg="#f0f0f2",
    content_bg="#f0f0f2",
    sidebar_bg="#e8e8eb",

    # Surfaces
    surface="#ffffff",
    surface_elevated="#f7f7f9",
    surface_hover="#f0f0f2",
    surface_pressed="#e8e8eb",

    # Borders
    border="#d0d0d6",
    border_subtle="#e0e0e4",
    border_focus="#1976d2",

    # Text
    text_primary="#1c1c1e",
    text_secondary="#3c3c43",
    text_muted="#8e8e93",
    text_disabled="#c7c7cc",

    # Accent
    accent="#1976d2",
    accent_hover="#1e88e5",
    accent_pressed="#1565c0",

    # Semantic
    success="#2e7d32",
    warning="#e65100",
    danger="#c62828",
    info="#1565c0",

    # Tables
    table_header_bg="#f0f0f2",
    table_header_text="#6e6e73",
    table_row_bg="#ffffff",
    table_row_alt="#f7f7f9",
    table_row_hover="#f0f0f2",
    table_row_selected="#e3f2fd",
    table_grid="#e8e8eb",
    table_row_system="#eaeef5",

    # Inputs
    input_bg="#ffffff",
    input_border="#d0d0d6",
    input_text="#1c1c1e",
    input_focus_border="#1976d2",

    # Scrollbar
    scrollbar_bg="#f0f0f2",
    scrollbar_handle="#c7c7cc",

    # Cards
    card_bg="#ffffff",
    card_border="#d0d0d6",
    panel_bg="#ffffff",

    # Secondary buttons
    btn_secondary_bg="#ffffff",
    btn_secondary_text="#1c1c1e",
    btn_secondary_border="#d0d0d6",
    btn_secondary_hover="#f0f0f2",

    # Primary buttons
    btn_primary_bg="#1976d2",
    btn_primary_text="#ffffff",
    btn_primary_hover="#1e88e5",
    btn_primary_pressed="#1565c0",
    btn_primary_disabled_bg="#e8e8eb",
    btn_primary_disabled_text="#c7c7cc",

    # Danger buttons
    btn_danger_bg="#ffffff",
    btn_danger_text="#c62828",
    btn_danger_border="#ffcdd2",
    btn_danger_hover="#ffebee",
    btn_danger_pressed="#ffcdd2",

    # Links
    link_text="#1565c0",
    link_hover="#0d47a1",
    link_pressed="#0d47a1",

    # Finding cards
    finding_bg="#ffffff",
    finding_border="#d0d0d6",
    finding_high_border="#ffcdd2",
    finding_severity_bg="#f0f0f2",

    # Perf
    perf_card_bg="#f7f7f9",
    perf_metric_bg="#f7f7f9",

    # Settings
    settings_group_bg="#ffffff",
    settings_group_border="#d0d0d6",

    # Combo
    combo_bg="#ffffff",
    combo_border="#d0d0d6",
    combo_text="#1c1c1e",
    combo_hover_border="#c7c7cc",
    combo_arrow="#6e6e73",
    combo_select_bg="#e3f2fd",

    # Spin
    spin_bg="#ffffff",
    spin_border="#d0d0d6",
    spin_text="#1c1c1e",
    spin_hover_border="#c7c7cc",
    spin_focus_border="#1976d2",

    # Check
    check_text="#1c1c1e",
    check_border="#c7c7cc",
    check_bg="#ffffff",
    check_checked_bg="#1976d2",
    check_checked_border="#1976d2",
    check_hover_border="#1976d2",

    # Device list
    device_list_bg="#ffffff",
    device_list_border="#d0d0d6",
    device_list_text="#1c1c1e",
    device_list_selected="#e3f2fd",
    device_list_hover="#f0f0f2",
)

CYBER_TOKENS: Final[ThemeTokens] = ThemeTokens(
    # Backgrounds — deep graphite / navy
    window_bg="#0b0e14",
    content_bg="#0b0e14",
    sidebar_bg="#080b10",

    # Surfaces
    surface="#12161e",
    surface_elevated="#181d27",
    surface_hover="#1c2230",
    surface_pressed="#0f131a",

    # Borders
    border="#1e2636",
    border_subtle="#161c28",
    border_focus="#00b4d8",

    # Text
    text_primary="#e0e6f0",
    text_secondary="#b0bac8",
    text_muted="#5c6a7a",
    text_disabled="#3a4555",

    # Accent — restrained cyan
    accent="#00b4d8",
    accent_hover="#22c8ea",
    accent_pressed="#0096b7",

    # Semantic
    success="#2dd4a0",
    warning="#f0a830",
    danger="#ef5350",
    info="#00b4d8",

    # Tables
    table_header_bg="#12161e",
    table_header_text="#5c6a7a",
    table_row_bg="#12161e",
    table_row_alt="#151a24",
    table_row_hover="#1c2230",
    table_row_selected="#0d2a3a",
    table_grid="#1e2636",
    table_row_system="#151a24",

    # Inputs
    input_bg="#12161e",
    input_border="#1e2636",
    input_text="#b0bac8",
    input_focus_border="#00b4d8",

    # Scrollbar
    scrollbar_bg="#12161e",
    scrollbar_handle="#2a3545",

    # Cards
    card_bg="#12161e",
    card_border="#1e2636",
    panel_bg="#12161e",

    # Secondary buttons
    btn_secondary_bg="#181d27",
    btn_secondary_text="#b0bac8",
    btn_secondary_border="#1e2636",
    btn_secondary_hover="#1c2230",

    # Primary buttons
    btn_primary_bg="#00b4d8",
    btn_primary_text="#0b0e14",
    btn_primary_hover="#22c8ea",
    btn_primary_pressed="#0096b7",
    btn_primary_disabled_bg="#181d27",
    btn_primary_disabled_text="#3a4555",

    # Danger buttons
    btn_danger_bg="#12161e",
    btn_danger_text="#ef5350",
    btn_danger_border="#3a1a1a",
    btn_danger_hover="#1a1214",
    btn_danger_pressed="#3a1a1a",

    # Links
    link_text="#00b4d8",
    link_hover="#22c8ea",
    link_pressed="#0096b7",

    # Finding cards
    finding_bg="#12161e",
    finding_border="#1e2636",
    finding_high_border="#3a1a1a",
    finding_severity_bg="#181d27",

    # Perf
    perf_card_bg="#0f131a",
    perf_metric_bg="#0f131a",

    # Settings
    settings_group_bg="#12161e",
    settings_group_border="#1e2636",

    # Combo
    combo_bg="#12161e",
    combo_border="#1e2636",
    combo_text="#b0bac8",
    combo_hover_border="#2a3545",
    combo_arrow="#5c6a7a",
    combo_select_bg="#0d2a3a",

    # Spin
    spin_bg="#12161e",
    spin_border="#1e2636",
    spin_text="#b0bac8",
    spin_hover_border="#2a3545",
    spin_focus_border="#00b4d8",

    # Check
    check_text="#b0bac8",
    check_border="#2a3545",
    check_bg="#12161e",
    check_checked_bg="#00b4d8",
    check_checked_border="#00b4d8",
    check_hover_border="#00b4d8",

    # Device list
    device_list_bg="#12161e",
    device_list_border="#1e2636",
    device_list_text="#b0bac8",
    device_list_selected="#0d2a3a",
    device_list_hover="#181d27",
)


# --------------------------------------------------------------------------- #
# CSS builder — single template, token-driven
# --------------------------------------------------------------------------- #

_CSS_TEMPLATE: Final[str] = """
QWidget {{
    background-color: {window_bg};
    color: {text_secondary};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}
QWidget#dashboard {{
    background-color: {content_bg};
}}
QFrame#panel {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 8px;
}}
QFrame#sectionRule {{
    background-color: {border};
    border: none;
}}
QWidget#updateBanner {{
    background-color: {surface};
    border: 1px solid {accent};
    border-radius: 8px;
}}
QLabel#sectionTitle {{
    color: {text_muted};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#muted {{
    color: {text_muted};
}}
QLabel#caption {{
    color: {text_secondary};
}}
QLabel#valueBig {{
    font-size: 30px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#value {{
    font-size: 20px;
    font-weight: 500;
    color: {text_secondary};
}}
QLabel#statusConnected {{
    color: {success};
    font-weight: 600;
}}
QLabel#statusWarn {{
    color: {warning};
    font-weight: 600;
}}
QLabel#statusError {{
    color: {danger};
    font-weight: 600;
}}
QProgressBar {{
    background-color: {surface_elevated};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: {text_secondary};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 4px;
}}
QTableWidget {{
    background-color: {table_row_bg};
    alternate-background-color: {table_row_alt};
    border: none;
    gridline-color: {table_grid};
    selection-background-color: {table_row_selected};
    color: {text_secondary};
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
}}
QTableWidget::item:hover {{
    background-color: {table_row_hover};
}}
QTableWidget::item:selected {{
    background-color: {table_row_selected};
}}
QLineEdit#processFilter {{
    background-color: {input_bg};
    border: 1px solid {input_border};
    border-radius: 6px;
    padding: 6px 10px;
    color: {input_text};
    selection-background-color: {table_row_selected};
}}
QLineEdit#processFilter:focus {{
    border-color: {input_focus_border};
}}
QPushButton#link {{
    color: {link_text};
    background: transparent;
    border: none;
    padding: 2px;
    font-size: 11px;
}}
QPushButton#link:hover {{
    color: {link_hover};
}}
QPushButton#link:pressed {{
    color: {link_pressed};
}}
QPushButton#primary {{
    background-color: {btn_primary_bg};
    color: {btn_primary_text};
    border: none;
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background-color: {btn_primary_hover};
}}
QPushButton#primary:pressed {{
    background-color: {btn_primary_pressed};
}}
QPushButton#primary:disabled {{
    background-color: {btn_primary_disabled_bg};
    color: {btn_primary_disabled_text};
}}
QPushButton#secondary {{
    background-color: {btn_secondary_bg};
    color: {btn_secondary_text};
    border: 1px solid {btn_secondary_border};
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: 500;
}}
QPushButton#secondary:hover {{
    background-color: {btn_secondary_hover};
}}
QPushButton#secondary:disabled {{
    background-color: {surface_elevated};
    color: {text_disabled};
    border-color: {border_subtle};
}}
QWidget[mono="true"] {{
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
}}
QLabel[level="elevated"] {{
    color: {warning};
}}
QLabel[level="high"] {{
    color: {danger};
}}
QLabel#setupTitle {{
    font-size: 26px;
    font-weight: 600;
    color: {text_primary};
}}
QListWidget#deviceList {{
    background-color: {device_list_bg};
    border: 1px solid {device_list_border};
    border-radius: 8px;
    color: {device_list_text};
    outline: none;
    padding: 4px;
}}
QListWidget#deviceList::item {{
    padding: 10px 12px;
    border-radius: 6px;
}}
QListWidget#deviceList::item:selected {{
    background-color: {device_list_selected};
}}
QListWidget#deviceList::item:hover {{
    background-color: {device_list_hover};
}}
QHeaderView::section {{
    background-color: {table_header_bg};
    color: {table_header_text};
    border: none;
    padding: 4px 8px;
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: {scrollbar_bg};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {scrollbar_handle};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QWidget#sidebar {{
    background-color: {sidebar_bg};
    border-right: 1px solid {border};
}}
QLabel#appTitle {{
    color: {text_primary};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0 8px;
}}
QLabel#navSection {{
    color: {text_muted};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 4px 8px 1px 8px;
}}
QPushButton#navButton {{
    background: transparent;
    color: {text_secondary};
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0;
    text-align: left;
    padding: 7px 10px 7px 10px;
    font-weight: 500;
}}
QPushButton#navButton:hover {{
    background-color: {surface_hover};
    color: {text_primary};
}}
QPushButton#navButton:focus {{
    background-color: {surface_hover};
    color: {text_primary};
}}
QPushButton#navButton:checked {{
    background-color: {surface_pressed};
    color: {text_primary};
    border-left: 2px solid {accent};
    font-weight: 600;
}}
QWidget#connectionStrip {{
    background-color: {sidebar_bg};
    border-bottom: 1px solid {border};
}}
QLabel#pageTitle {{
    font-size: 22px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#pageSubtitle {{
    color: {text_muted};
    font-size: 12px;
}}
QWidget#metricCard {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 8px;
}}
QLabel#cardCaption {{
    color: {text_muted};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#cardValue {{
    color: {text_primary};
    font-size: 30px;
    font-weight: 600;
}}
QLabel#cardValueHigh {{
    color: {danger};
    font-size: 30px;
    font-weight: 600;
}}
QLabel#cardValueMedium {{
    color: {warning};
    font-size: 30px;
    font-weight: 600;
}}
QLabel#securityStatus {{
    color: {text_secondary};
}}
QLabel#securityStatusHigh {{
    color: {danger};
    font-weight: 600;
}}
QLabel#securityStatusMedium {{
    color: {warning};
    font-weight: 600;
}}
QLabel#emptyTitle {{
    color: {text_secondary};
    font-size: 15px;
    font-weight: 600;
}}
QLabel#emptyBody {{
    color: {text_muted};
    font-size: 12px;
}}
QLabel#deviceEmptyTitle {{
    color: {text_muted};
    font-size: 16px;
    font-weight: 600;
    padding: 32px 16px;
}}
QWidget#findingCard {{
    background-color: {finding_bg};
    border: 1px solid {finding_border};
    border-left: 3px solid {warning};
    border-radius: 8px;
}}
QWidget#findingCardHigh {{
    background-color: {finding_bg};
    border: 1px solid {finding_high_border};
    border-left: 3px solid {danger};
    border-radius: 8px;
}}
QLabel#findingSeverity {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 8px;
    border-radius: 4px;
    background-color: {finding_severity_bg};
}}
QLabel#findingSeverity[level="high"] {{
    color: {danger};
}}
QLabel#findingSeverity[level="elevated"] {{
    color: {warning};
}}
QLabel#findingSeverity[level="info"] {{
    color: {info};
}}
QWidget#diagCardInfo {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-left: 3px solid {info};
    border-radius: 8px;
}}
QWidget#evidenceRow {{
    background-color: {surface_elevated};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#diagField {{
    color: {text_muted};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#findingRule {{
    color: {text_secondary};
    font-weight: 600;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
    font-size: 12px;
}}
QLabel#findingReason {{
    color: {text_secondary};
}}
/* --- Performance Intelligence --- */
QLabel#perfStateBadge {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: 6px 12px;
    border-radius: 6px;
    background-color: {perf_metric_bg};
    border: 1px solid {border};
}}
QLabel#perfStateBadge[level="high"] {{
    color: {danger};
    border-color: {danger};
}}
QLabel#perfStateBadge[level="elevated"] {{
    color: {warning};
    border-color: {warning};
}}
QLabel#perfStateBadge[level="info"] {{
    color: {success};
    border-color: {success};
}}
QLabel#perfStateBadge[level="muted"] {{
    color: {text_muted};
}}
QLabel#perfScoreBadge {{
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 5px 12px;
    border-radius: 6px;
    background-color: {perf_metric_bg};
    border: 1px solid {border};
}}
QLabel#perfScoreBadge[level="high"] {{
    color: {danger};
    border-color: {danger};
}}
QLabel#perfScoreBadge[level="elevated"] {{
    color: {warning};
    border-color: {warning};
}}
QLabel#perfScoreBadge[level="info"] {{
    color: {success};
    border-color: {success};
}}
QLabel#perfScoreBadge[level="muted"] {{
    color: {text_muted};
}}
QWidget#perfExplanationCard {{
    background-color: {surface_elevated};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#perfWhyTitle {{
    color: {text_primary};
    font-weight: 700;
    font-size: 13px;
}}
QLabel#whySectionTitle {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
}}
QWidget#perfEpisodeCard {{
    background-color: {surface_elevated};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#perfEpisodeSummary {{
    color: {text_secondary};
    font-size: 12px;
}}
QFrame#perfMetricCard {{
    background-color: {perf_metric_bg};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#perfMetricLabel {{
    color: {text_secondary};
    font-weight: 600;
    font-size: 12px;
}}
QLabel#perfMetricValue {{
    color: {text_primary};
    font-weight: 700;
    font-size: 22px;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
}}
QLabel#perfMetricBaseline {{
    color: {text_secondary};
    font-size: 11px;
}}
QLabel#perfMetricOcc {{
    color: {text_muted};
    font-size: 11px;
}}
QLabel#perfMetricEvidence {{
    color: {text_secondary};
    font-size: 11px;
}}
QLabel#evidenceGroupTitle {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    margin-top: 4px;
}}
QWidget#perfSummary {{
    background-color: {surface_elevated};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 10px;
}}
QLabel#perfSummaryMetrics {{
    color: {text_secondary};
    font-size: 12px;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
}}
QPushButton#perfTimelineButton {{
    color: {success};
    background-color: transparent;
    border: 1px solid {success};
    border-radius: 5px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#perfTimelineButton:hover {{
    background-color: {surface_hover};
}}
/* --- Settings page --- */
QComboBox#settingsCombo {{
    background-color: {combo_bg};
    border: 1px solid {combo_border};
    border-radius: 6px;
    padding: 6px 10px;
    color: {combo_text};
    min-height: 24px;
}}
QComboBox#settingsCombo:hover {{
    border-color: {combo_hover_border};
}}
QComboBox#settingsCombo::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox#settingsCombo::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {combo_arrow};
    margin-right: 8px;
}}
QComboBox#settingsCombo QAbstractItemView {{
    background-color: {combo_bg};
    border: 1px solid {combo_border};
    color: {combo_text};
    selection-background-color: {combo_select_bg};
    padding: 4px;
}}
QSpinBox#settingsSpin {{
    background-color: {spin_bg};
    border: 1px solid {spin_border};
    border-radius: 6px;
    padding: 6px 10px;
    color: {spin_text};
    min-height: 24px;
}}
QSpinBox#settingsSpin:hover {{
    border-color: {spin_hover_border};
}}
QSpinBox#settingsSpin:focus {{
    border-color: {spin_focus_border};
}}
QCheckBox#settingsCheck {{
    color: {check_text};
    spacing: 8px;
}}
QCheckBox#settingsCheck::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {check_border};
    background-color: {check_bg};
}}
QCheckBox#settingsCheck::indicator:checked {{
    background-color: {check_checked_bg};
    border-color: {check_checked_border};
}}
QCheckBox#settingsCheck::indicator:hover {{
    border-color: {check_hover_border};
}}
QFrame#settingsGroup {{
    background-color: {settings_group_bg};
    border: 1px solid {settings_group_border};
    border-radius: 8px;
    padding: 4px;
}}
QPushButton#danger {{
    background-color: {btn_danger_bg};
    color: {btn_danger_text};
    border: 1px solid {btn_danger_border};
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: 600;
}}
QPushButton#danger:hover {{
    background-color: {btn_danger_hover};
}}
QPushButton#danger:pressed {{
    background-color: {btn_danger_pressed};
}}
"""


# --------------------------------------------------------------------------- #
# Token lookup
# --------------------------------------------------------------------------- #

_TOKEN_MAP: Final[dict[str, ThemeTokens]] = {
    "dark": DARK_TOKENS,
    "light": LIGHT_TOKENS,
    "cyber": CYBER_TOKENS,
}


def _resolve_theme(theme: str) -> ThemeTokens:
    """Resolve a theme name to its token set.

    ``"system"`` falls through to the caller — it should never reach here
    because :func:`apply_theme` resolves it first.
    """
    return _TOKEN_MAP.get(theme, DARK_TOKENS)


def build_style(theme: str) -> str:
    """Render the full CSS for *theme* by filling the template with tokens."""
    tokens = _resolve_theme(theme)
    return _CSS_TEMPLATE.format_map(asdict(tokens))


# --------------------------------------------------------------------------- #
# Legacy named styles (kept for backward compat with tests / imports)
# --------------------------------------------------------------------------- #

DARK_STYLE: Final[str] = build_style("dark")
LIGHT_STYLE: Final[str] = build_style("light")
CYBER_STYLE: Final[str] = build_style("cyber")


# --------------------------------------------------------------------------- #
# System detection & application
# --------------------------------------------------------------------------- #

def is_system_dark() -> bool:
    """Detect Windows dark mode via the registry.

    Falls back to ``True`` (dark) when the key is missing or unreadable,
    which is the safe default for this application.
    """
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception:
        return True


# The token set for the theme currently applied to the running application.
_ACTIVE_TOKENS: ThemeTokens = DARK_TOKENS


def apply_theme(app: QApplication, theme: str) -> None:
    """Apply the given theme to the running application."""
    global _ACTIVE_TOKENS
    if theme == "system":
        resolved = "dark" if is_system_dark() else "light"
    else:
        resolved = theme
    _ACTIVE_TOKENS = _resolve_theme(resolved)
    app.setStyleSheet(build_style(resolved))


def active_tokens() -> ThemeTokens:
    """Return the token set for the currently applied theme.

    Defaults to the Dark token set before any theme has been applied. UI code
    that paints widgets imperatively (outside the stylesheet) should read
    colors from here so it stays in sync with theme switching.
    """
    return _ACTIVE_TOKENS


# --------------------------------------------------------------------------- #
# Backward-compat helpers (used by the previous Light placeholder approach)
# --------------------------------------------------------------------------- #

def get_style(theme: str) -> str:
    """Return the stylesheet string for the given theme."""
    return build_style(theme)
