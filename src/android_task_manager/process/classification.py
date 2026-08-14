"""Heuristic process classification.

This is a deliberately simple, documented classification — not a perfect
Android process taxonomy. It is good enough for a system monitor surface view.
"""

from __future__ import annotations

from .models import ProcessCategory

#: Android reserves uid 0..9999 for system accounts (root=0, system=1000,
#: radio, shell, etc.). Application (app) uids start at AID_APP = 10000.
_AID_APP = 10000


def is_kernel_thread_name(name: str) -> bool:
    """True when a name looks like a kernel thread, e.g. ``[kworker/0:1]``.

    Linux shows kernel threads bracketed in procps/ps listings. This is the
    practical signal used here; it is not a guarantee for every kernel.
    """
    stripped = name.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def classify_process(name: str, uid: int | None) -> ProcessCategory:
    """Classify a process by (name, uid).

    Rules (in order):
      1. Bracket-wrapped kernel thread names -> KERNEL_THREAD.
      2. Unknown uid (e.g. a process only seen in top) -> SYSTEM, since ps is
         the authoritative source for real user apps and we have no uid.
      3. uid below AID_APP (10000) -> SYSTEM / service.
      4. otherwise -> USER / application.

    Note that some system processes have no brackets and app detection relies
    on the uid threshold; this is documented as imperfect rather than treated
    as exact androids classification.
    """
    if is_kernel_thread_name(name):
        return ProcessCategory.KERNEL_THREAD
    if uid is None:
        return ProcessCategory.SYSTEM
    if uid < _AID_APP:
        return ProcessCategory.SYSTEM
    return ProcessCategory.USER