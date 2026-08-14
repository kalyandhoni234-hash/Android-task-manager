"""Shared dark theme used by the whole dashboard (objectName-driven)."""

from __future__ import annotations

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
QLabel#sectionTitle {
    color: #7a8794;
    font-size: 11px;
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
"""