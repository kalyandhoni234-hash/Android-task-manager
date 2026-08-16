"""Shared dark theme used by the whole dashboard (objectName-driven)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget


def repolish(widget: QWidget) -> None:
    """Re-apply the app stylesheet to *widget* after an objectName change.

    Qt only evaluates an objectName-based stylesheet rule when a widget is
    polished; changing ``objectName`` at runtime without re-polishing leaves
    the old color/weight in place. Widgets that swap objectNames to reflect
    state (connection, severity) must call this after every swap.
    """
    app = QApplication.instance()
    if app is not None:
        app.style().unpolish(widget)
        app.style().polish(widget)


DARK_STYLE = """
QWidget {
    background-color: #14181d;
    color: #d8dee6;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QWidget#dashboard {
    background-color: #14181d;
}
QFrame#panel {
    background-color: #1d232b;
    border: 1px solid #2a323c;
    border-radius: 8px;
}
QFrame#sectionRule {
    background-color: #2a323c;
    border: none;
}
QWidget#updateBanner {
    background-color: #1d232b;
    border: 1px solid #2f6fed;
    border-radius: 8px;
}
QLabel#sectionTitle {
    color: #7a8794;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#muted {
    color: #7a8794;
}
QLabel#caption {
    color: #aab4c0;
}
QLabel#valueBig {
    font-size: 30px;
    font-weight: 600;
    color: #e8eef5;
}
QLabel#value {
    font-size: 20px;
    font-weight: 500;
    color: #d8dee6;
}
QLabel#statusConnected {
    color: #3ddc84;
    font-weight: 600;
}
QLabel#statusWarn {
    color: #f5a524;
    font-weight: 600;
}
QLabel#statusError {
    color: #ff5f56;
    font-weight: 600;
}
QProgressBar {
    background-color: #232b35;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #d8dee6;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #3d9be9;
    border-radius: 4px;
}
QTableWidget {
    background-color: #1d232b;
    alternate-background-color: #202833;
    border: none;
    gridline-color: transparent;
    selection-background-color: #2b3a4d;
    color: #d8dee6;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
}
QTableWidget::item:hover {
    background-color: #242c36;
}
QTableWidget::item:selected {
    background-color: #2b3a4d;
}
QLineEdit#processFilter {
    background-color: #1d232b;
    border: 1px solid #2a323c;
    border-radius: 6px;
    padding: 6px 10px;
    color: #d8dee6;
    selection-background-color: #2b3a4d;
}
QLineEdit#processFilter:focus {
    border-color: #3d9be9;
}
QPushButton#link {
    color: #3d9be9;
    background: transparent;
    border: none;
    padding: 2px;
    font-size: 11px;
}
QPushButton#link:hover {
    color: #6db5f0;
}
QPushButton#link:pressed {
    color: #2a7fc9;
}
QPushButton#primary {
    background-color: #2f6fed;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: 600;
}
QPushButton#primary:hover {
    background-color: #3d7df5;
}
QPushButton#primary:pressed {
    background-color: #2559c2;
}
QPushButton#primary:disabled {
    background-color: #232b35;
    color: #5c6672;
}
QPushButton#secondary {
    background-color: #232b35;
    color: #d8dee6;
    border: 1px solid #2a323c;
    border-radius: 6px;
    padding: 9px 20px;
    font-weight: 500;
}
QPushButton#secondary:hover {
    background-color: #2b3541;
}
QPushButton#secondary:disabled {
    background-color: #1d232b;
    color: #5c6672;
    border-color: #232b35;
}
QWidget[mono="true"] {
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
}
QLabel[level="elevated"] {
    color: #f5a524;
}
QLabel[level="high"] {
    color: #ff5f56;
}
QLabel#setupTitle {
    font-size: 26px;
    font-weight: 600;
    color: #e8eef5;
}
QListWidget#deviceList {
    background-color: #1d232b;
    border: 1px solid #2a323c;
    border-radius: 8px;
    color: #d8dee6;
    outline: none;
    padding: 4px;
}
QListWidget#deviceList::item {
    padding: 10px 12px;
    border-radius: 6px;
}
QListWidget#deviceList::item:selected {
    background-color: #2b3a4d;
}
QListWidget#deviceList::item:hover {
    background-color: #232b35;
}
QHeaderView::section {
    background-color: #232b35;
    color: #7a8794;
    border: none;
    padding: 4px 8px;
    font-weight: 600;
}
QScrollBar:vertical {
    background: #1d232b;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3a4552;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QWidget#sidebar {
    background-color: #10141a;
    border-right: 1px solid #2a323c;
}
QLabel#appTitle {
    color: #d8dee6;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 0 8px;
}
QLabel#navSection {
    color: #5c6672;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 4px 8px 1px 8px;
}
QPushButton#navButton {
    background: transparent;
    color: #aab4c0;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0;
    text-align: left;
    padding: 7px 10px 7px 10px;
    font-weight: 500;
}
QPushButton#navButton:hover {
    background-color: #1d232b;
    color: #d8dee6;
}
QPushButton#navButton:focus {
    background-color: #1d232b;
    color: #d8dee6;
}
QPushButton#navButton:checked {
    background-color: #1b2430;
    color: #e8eef5;
    border-left: 2px solid #2f6fed;
    font-weight: 600;
}
QWidget#connectionStrip {
    background-color: #10141a;
    border-bottom: 1px solid #2a323c;
}
QLabel#pageTitle {
    font-size: 22px;
    font-weight: 600;
    color: #e8eef5;
}
QLabel#pageSubtitle {
    color: #7a8794;
    font-size: 12px;
}
QWidget#metricCard {
    background-color: #1d232b;
    border: 1px solid #2a323c;
    border-radius: 8px;
}
QLabel#cardCaption {
    color: #7a8794;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#cardValue {
    color: #e8eef5;
    font-size: 30px;
    font-weight: 600;
}
QLabel#cardValueHigh {
    color: #ff5f56;
    font-size: 30px;
    font-weight: 600;
}
QLabel#cardValueMedium {
    color: #f5a524;
    font-size: 30px;
    font-weight: 600;
}
QLabel#securityStatus {
    color: #aab4c0;
}
QLabel#securityStatusHigh {
    color: #ff5f56;
    font-weight: 600;
}
QLabel#securityStatusMedium {
    color: #f5a524;
    font-weight: 600;
}
QLabel#emptyTitle {
    color: #aab4c0;
    font-size: 15px;
    font-weight: 600;
}
QLabel#emptyBody {
    color: #7a8794;
    font-size: 12px;
}
QLabel#deviceEmptyTitle {
    color: #7a8794;
    font-size: 16px;
    font-weight: 600;
    padding: 32px 16px;
}
QWidget#findingCard {
    background-color: #1d232b;
    border: 1px solid #2a323c;
    border-left: 3px solid #f5a524;
    border-radius: 8px;
}
QWidget#findingCardHigh {
    background-color: #1d232b;
    border: 1px solid #4a2f33;
    border-left: 3px solid #ff5f56;
    border-radius: 8px;
}
QLabel#findingSeverity {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 2px 8px;
    border-radius: 4px;
    background-color: #232b35;
}
QLabel#findingSeverity[level="high"] {
    color: #ff5f56;
}
QLabel#findingSeverity[level="elevated"] {
    color: #f5a524;
}
QLabel#findingSeverity[level="info"] {
    color: #3d9be9;
}
QWidget#diagCardInfo {
    background-color: #1d232b;
    border: 1px solid #2a323c;
    border-left: 3px solid #3d9be9;
    border-radius: 8px;
}
QLabel#diagField {
    color: #7a8794;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#findingRule {
    color: #d8dee6;
    font-weight: 600;
    font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
    font-size: 12px;
}
QLabel#findingReason {
    color: #aab4c0;
}
"""