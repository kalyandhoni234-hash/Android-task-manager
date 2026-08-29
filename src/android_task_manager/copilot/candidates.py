"""Deterministic candidate-generation for Copilot.

When the user asks "what should I close / free up RAM for [game]?",
this layer produces a bounded, ranked list of *candidates* plus an
explicit *protected* set. It is pure and deterministic and reuses the
existing intelligence primitives — it never asks Gemini to decide
what is safe.

Sources of truth (reused, not duplicated):

* per-app aggregation + foreground/background state from
  :class:`~android_task_manager.background.models.BackgroundAppsSnapshot`
  (already built by the v0.8.1 background-app pipeline);
* the currently resumed (foreground) package from
  :class:`~android_task_manager.background.models.ForegroundSnapshot`;
* authoreitative category + capability from the application inventory
  (``user_packages``) and the action layer.

Ranking signals (deterministic): user category, background state,
memory share, capability (force-stop supported) and CPU. Protected
system/kernel processes are always excluded from candidates.
"""

from __future__ import annotations

from ..applications.models import AppCategory, ApplicationSnapshot
from ..background.models import (
    BackgroundAppEntry,
    BackgroundAppsSnapshot,
    BackgroundAppState,
    ForegroundSnapshot,
)
from ..memory.models import MemorySnapshot
from ..recommend.engine import is_valid_package_name
from .intent import INTENT_CLOSE_APP, INTENT_GAMING
from .models import KillCandidate, ProcessSafetyClass, ProtectedProcess

#: Candidate cardinality — a short, focused list is more useful than a dump.
_MAX_CANDIDATES = 6


def _is_user_package(package: str, user_packages: set[str] | None) -> bool:
    if user_packages is None:
        return is_valid_package_name(package)
    return package in user_packages


def build_candidates(
    *,
    background: BackgroundAppsSnapshot | None,
    foreground: ForegroundSnapshot | None,
    memory: MemorySnapshot | None,
    app_snapshot: ApplicationSnapshot | None,
    user_packages: set[str] | None,
    intent: str = "general",
    max_candidates: int = _MAX_CANDIDATES,
) -> tuple[tuple[KillCandidate, ...], tuple[ProtectedProcess, ...]]:
    """Return (candidates, protected) for a "what should I close?" intent.

    Only produces candidates when the intent is about closing/freeing
    resources (gaming or close-app). Returns empty candidate tuples for
    other intents, so the deterministic layer stays silent unless asked.
    """
    if intent not in (INTENT_GAMING, INTENT_CLOSE_APP):
        return (), ()
    if background is None or not background.entries:
        return (), ()

    foreground_pkg = foreground.package_name if (
        foreground is not None and foreground.available
    ) else None

    # Build the protected set from the application inventory: system apps
    # are always protected; user apps are protected when foreground; any
    # process that is not a verified user package is protected by definition
    # and never surfaced as a candidate.
    protected: list[ProtectedProcess] = []
    seen_protected: set[str] = set()

    def _add_protected(name: str, safety: ProcessSafetyClass, reason: str) -> None:
        key = (name, safety.value)
        if key in seen_protected or len(protected) >= 12:
            return
        seen_protected.add(key)
        protected.append(ProtectedProcess(name=name, safety=safety, reason=reason))

    # Deterministic app category map.
    app_category: dict[str, AppCategory] = {}
    if app_snapshot is not None:
        for app in app_snapshot.applications:
            app_category[app.package_name] = app.category

    candidates: list[KillCandidate] = []
    for entry in background.entries:
        pkg = entry.package_name
        if not is_valid_package_name(pkg):
            continue
        is_user = _is_user_package(pkg, user_packages)
        category = app_category.get(pkg, AppCategory.USER if is_user else AppCategory.UNKNOWN)
        if category is AppCategory.SYSTEM:
            _add_protected(
                pkg,
                ProcessSafetyClass.SYSTEM_PROCESS,
                "system application — never a safe kill target",
            )
            continue
        if not is_user:
            _add_protected(
                pkg,
                ProcessSafetyClass.SYSTEM_PROCESS,
                "not a verified user application",
            )
            continue
        if pkg == foreground_pkg:
            _add_protected(
                pkg,
                ProcessSafetyClass.SYSTEM_PROCESS,
                "currently in the foreground — closing it would interrupt what you are doing",
            )
            continue
        state = entry.state
        is_background = state is BackgroundAppState.BACKGROUND
        # Rank memory share; prefer background user apps with capability.
        reason_lines: list[str] = []
        if is_background:
            reason_lines.append("background user application")
        elif state is BackgroundAppState.UNKNOWN:
            reason_lines.append("user application without a confirmed foreground state")
        else:
            reason_lines.append("user application (foreground — close only if you accept interrupting it)")
        candidates.append(
            KillCandidate(
                name=pkg,
                category=category.value,
                safety=ProcessSafetyClass.SAFE_CANDIDATE,
                memory_percent=entry.memory_percent,
                cpu_percent=entry.cpu_percent,
                reason="; ".join(reason_lines),
                estimated_reclaimable_kb=_estimate_reclaimable(
                    entry, memory, is_background
                ),
            )
        )

    # Deterministic ranking: memory share desc (the resource we are freeing),
    # background-first, then CPU desc, then name for stable order.
    candidates.sort(
        key=lambda c: (
            0 if "background user application" in c.reason else 1,
            -(c.memory_percent or 0.0),
            -(c.cpu_percent or 0.0),
            c.name,
        )
    )
    return tuple(candidates[:max_candidates]), tuple(protected)


def _estimate_reclaimable(
    entry: BackgroundAppEntry,
    memory: MemorySnapshot | None,
    is_background: bool,
) -> int | None:
    """Best-effort estimated reclaimable memory in KiB for one candidate.

    Uses the aggregated per-app memory estimate when available; otherwise
    derives it from the candidate's memory share of total RAM. Never
    invents a number when nothing supports it.
    """
    if not is_background:
        return None
    if entry.memory_kb is not None and entry.memory_kb > 0:
        return entry.memory_kb
    if memory is not None and memory.total_kb > 0 and entry.memory_percent is not None:
        return int(memory.total_kb * entry.memory_percent / 100.0)
    return None


__all__ = [
    "build_candidates",
]
