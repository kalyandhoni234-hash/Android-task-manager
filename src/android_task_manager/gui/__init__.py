"""GUI package for the Android Task Manager.

This package provides a PySide6-based desktop dashboard that consumes the same
normalized snapshots (CPUSnapshot, MemorySnapshot, BatterySnapshot,
ProcessSnapshot) that the terminal renderer uses.

Architecture
------------
ADB → ConnectionManager → Collectors → Normalized snapshots
                                                ↓
                                    MonitorWorker (background thread)
                                                ↓
                                     Qt signals → GUI widgets

The GUI never imports subprocess, never runs adb commands directly, and never
duplicates collector logic. All ADB work happens in a background QThread.
"""
