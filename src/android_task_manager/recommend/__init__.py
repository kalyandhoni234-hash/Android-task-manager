"""Recommendation engine — deterministic, evidence-derived suggestions.

The "observation → finding → recommendation → action" chain: consumes
health findings (+ the process snapshot for concrete targets) and produces
ordered recommendations. Destructive actions are never automation-ready;
targets are validated package names.
"""

from .engine import is_valid_package_name, recommend
from .models import (
    RECOMMENDATION_SEVERITY_CRITICAL,
    RECOMMENDATION_SEVERITY_INFO,
    RECOMMENDATION_SEVERITY_WARNING,
    Recommendation,
)

__all__ = [
    "RECOMMENDATION_SEVERITY_CRITICAL",
    "RECOMMENDATION_SEVERITY_INFO",
    "RECOMMENDATION_SEVERITY_WARNING",
    "Recommendation",
    "is_valid_package_name",
    "recommend",
]