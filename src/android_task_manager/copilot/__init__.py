"""AI Copilot for Android Task Manager.

Context-aware AI assistant that helps users understand device state,
diagnose performance problems, and learn how the application works.

The Copilot is purely read-only: it inspects, explains, and recommends.
It never executes ADB commands or modifies device state.

Architecture (safety boundary):
    Live Android data
        -> deterministic collectors
        -> deterministic safety/classification (copilot.safety)
        -> safe structured context (copilot.context)
        -> Gemini (copilot.providers)
        -> explanation / recommendation (copilot.prompts/service)

Gemini is the reasoning layer only. Deterministic layers (safety,
candidates, intent) remain authoritative for what is ever safe to act on.
"""

from .candidates import build_candidates
from .context import build_context
from .intent import classify_intent
from .models import (
    CopilotContext,
    CopilotMessage,
    CopilotRequest,
    CopilotResponse,
    CopilotResult,
    CopilotRole,
    KillCandidate,
    MessageStatus,
    ProcessSafetyClass,
    ProtectedProcess,
    SafeApp,
    SafeFinding,
    SafeProcess,
    SafeRecommendation,
)
from .providers import GeminiProvider, LLMProvider, LLMProviderError
from .settings import CopilotConfig, load_config, save_config

__all__ = [
    "CopilotConfig",
    "CopilotContext",
    "CopilotMessage",
    "CopilotRequest",
    "CopilotResponse",
    "CopilotResult",
    "CopilotRole",
    "GeminiProvider",
    "KillCandidate",
    "LLMProvider",
    "LLMProviderError",
    "MessageStatus",
    "ProcessSafetyClass",
    "ProtectedProcess",
    "SafeApp",
    "SafeFinding",
    "SafeProcess",
    "SafeRecommendation",
    "build_candidates",
    "build_context",
    "classify_intent",
    "load_config",
    "save_config",
]
