"""Deterministic, lightweight intent classification for Copilot.

The Copilot should know *why* the user is asking before it frames an
answer. Rather than a heavy ML classifier, this module matches the user's
query against a small, documented set of regex intents. It is pure and
deterministic: the same query always yields the same intent.

Each intent is only a *hint* to the prompt builder about which subsystem
to emphasize. It never grants the LLM any authority — the deterministic
safety and recommendation layers remain the sole source of truth for
"what can I act on".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Fallback when no intent matches.
INTENT_GENERAL = "general"
INTENT_GAMING = "gaming"
INTENT_SLOW = "slow"
INTENT_BATTERY = "battery"
INTENT_CPU = "cpu"
INTENT_MEMORY = "memory"
INTENT_STORAGE = "storage"
INTENT_OVERHEAT = "overheat"
INTENT_HEALTH = "health"
INTENT_DIAGNOSTIC = "diagnostic"
INTENT_PERFORMANCE = "performance"
INTENT_NETWORK = "network"
INTENT_PROCESS = "process"
INTENT_CLOSE_APP = "close_app"
INTENT_WHAT_WRONG = "what_wrong"

_KNOWN_INTENTS = (
    INTENT_GENERAL,
    INTENT_GAMING,
    INTENT_SLOW,
    INTENT_BATTERY,
    INTENT_CPU,
    INTENT_MEMORY,
    INTENT_STORAGE,
    INTENT_OVERHEAT,
    INTENT_HEALTH,
    INTENT_DIAGNOSTIC,
    INTENT_PERFORMANCE,
    INTENT_NETWORK,
    INTENT_PROCESS,
    INTENT_CLOSE_APP,
    INTENT_WHAT_WRONG,
)


@dataclass(frozen=True)
class IntentRule:
    """One intent rule: a name and a set of case-insensitive regexes."""

    name: str
    patterns: tuple[str, ...]

    def match(self, text: str) -> bool:
        return any(re.search(p, text) for p in self.patterns)


#: Order matters — first rule that matches wins. More-specific intents
#: (single subsystem) are matched before the broad ``what_wrong`` / ``health``
#: intents, so a query about one subsystem routes there, and only genuinely
#: generic "is something wrong / assess my device" queries reach ``what_wrong``.
_INTENT_RULES = (
    IntentRule(
        INTENT_GAMING,
        (
            r"\b(play|game|gaming)\b",
            r"close.*\b(game|app|application)s?\b",
            r"\bzooba\b",
            r"maximum\s+ram\s+for",
            r"free\s+(up\s+)?ram",
            r"optimiz.*\b(game|gaming|performance)\b",
        ),
    ),
    IntentRule(
        INTENT_CLOSE_APP,
        (
            r"\b(close|kill|stop|clear|quit|force\s*stop)\b",
            r"what\s+should\s+i\s+close",
            r"which\s+app(s)?\s+(can|should)",
        ),
    ),
    IntentRule(
        INTENT_OVERHEAT,
        (r"\b(overheat(ing)?|over\s?heat|hot|temperature)\b",),
    ),
    IntentRule(
        INTENT_BATTERY,
        (r"\bbattery\b|draining|drain|charge\b",),
    ),
    IntentRule(
        INTENT_NETWORK,
        (
            r"\bnetwork\b|\bwifi\b|\bwlan\b|\bcellular\b|\bdata\b|internet|"
            r"connect(ed|ivity|ion)",
        ),
    ),
    IntentRule(
        INTENT_CPU,
        (r"\bcpu\b|\bcpu\s*usage\b|processor\s*usage",),
    ),
    IntentRule(
        INTENT_MEMORY,
        (r"\bram\b|\bmemory\b|consuming ram|eating ram",),
    ),
    IntentRule(
        INTENT_STORAGE,
        (r"\bstorage\b|\bfull\b|\bdisk\b|\bspace\b",),
    ),
    IntentRule(
        INTENT_PERFORMANCE,
        (r"\bperformance\b|why\s+did\s+performance",),
    ),
    IntentRule(
        INTENT_SLOW,
        (
            r"\b(slow|lag(?:ging|gy)?|stutter(?:ing)?|sluggish|freez(e|ing))\b",
        ),
    ),
    IntentRule(
        INTENT_PROCESS,
        (r"\bprocess(es)?\b|\bpid\b|\bapp\s*is\s*running\b",),
    ),
    IntentRule(
        INTENT_DIAGNOSTIC,
        (r"\bdiagnostic\b|what\s+triggered\b|explain\s+this\b",),
    ),
    IntentRule(
        INTENT_WHAT_WRONG,
        (
            # "What's wrong with ...?" / "what is the problem"
            r"what('?s|\sis)\s+(wrong\s+with|the\s+problem)",
            # "Is something / anything wrong ...?"
            r"\b(something|anything)\s+wrong",
            # "Is my <device> <okay|fine|healthy|doing|alright ...>?"
            r"\bis\s+my\s+(phone|device)\s+(ok|okay|fine|healthy|alright|"
            r"doing|wrong)\b",
            # "How is my <device> doing?"
            r"\bhow\s+is\s+(my\s+)?(phone|device)\s+doing\b",
            # "<device> have/got any problems/issues?"
            r"\b(have|has|got|having)\s+(any\s+)?(problems?|issues?|trouble)\b",
        ),
    ),
    IntentRule(
        INTENT_HEALTH,
        (r"\bhealth\b|score\b|is\s+my\s+(phone|device)\b",),
    ),
)


def classify_intent(query: str) -> str:
    """Return the deterministic intent name for *query*.

    The classification is intentionally lightweight and explainable: a
    small list of regex rules, first match wins, fall back to
    ``INTENT_GENERAL``.
    """
    text = query.lower()
    for rule in _INTENT_RULES:
        if rule.match(text):
            return rule.name
    return INTENT_GENERAL


__all__ = [
    "INTENT_BATTERY",
    "INTENT_CLOSE_APP",
    "INTENT_CPU",
    "INTENT_DIAGNOSTIC",
    "INTENT_GAMING",
    "INTENT_GENERAL",
    "INTENT_HEALTH",
    "INTENT_MEMORY",
    "INTENT_NETWORK",
    "INTENT_OVERHEAT",
    "INTENT_PERFORMANCE",
    "INTENT_PROCESS",
    "INTENT_SLOW",
    "INTENT_STORAGE",
    "INTENT_WHAT_WRONG",
    "classify_intent",
]
