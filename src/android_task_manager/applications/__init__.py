"""Application inventory and details: what is installed on the device."""

from __future__ import annotations

from .collector import ApplicationCollector
from .models import (
    AppCategory,
    AppDetails,
    AppInfo,
    ApplicationSnapshot,
)
from .parser import (
    build_inventory,
    category_from_flags,
    enabled_from_value,
    install_location_for,
    parse_app_details,
    parse_inventory_lines,
    parse_name_list,
)

__all__ = [
    "AppCategory",
    "AppDetails",
    "AppInfo",
    "ApplicationCollector",
    "ApplicationSnapshot",
    "build_inventory",
    "category_from_flags",
    "enabled_from_value",
    "install_location_for",
    "parse_app_details",
    "parse_inventory_lines",
    "parse_name_list",
]