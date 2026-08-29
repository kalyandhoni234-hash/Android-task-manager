"""Copilot data models — controlled, serializable schemas.

All data that reaches the LLM is derived from these models. The LLM
never receives raw Python objects, process snapshots, or device data
structures directly.

These schemas are deliberately narrow: only the fields the reasoning
layer genuinely needs are carried, and every field is either a scalar
or a ``frozen`` structured type. Nothing here can store an API key, a
GPU/CPU raw dump, or an unfiltered process/package table.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProcessSafetyClass(Enum):
    """Deterministic process classification BEFORE LLM sees data."""

    SAFE_CANDIDATE = "safe_candidate"
    USER_APP = "user_app"
    SYSTEM_PROCESS = "system_process"
    CRITICAL_SYSTEM = "critical_system"
    UNKNOWN = "unknown"


class CopilotRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(Enum):
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class SafeProcess:
    """A process pre-classified for safe LLM consumption.

    ``capability`` mirrors the deterministic action-layer outcome (e.g.
    ``"force_stop"`` when force-stop is actually permitted for this
    target) — the Copilot can *mention* it but never fires it. It is
    ``None`` when the target is not a validated package that the action
    layer would act on.
    """

    pid: int
    name: str
    category: ProcessSafetyClass
    cpu_percent: float | None
    memory_percent: float | None
    package: str | None = None
    uid: int | None = None
    state: str | None = None
    capability: str | None = None


@dataclass(frozen=True)
class SafeApp:
    """One installed application pre-screened for LLM consumption.

    No APK path, installer, flags, activity/service lists or permission
    data is ever exposed — only identity, category and deterministic
    action capability.
    """

    package_name: str
    category: str
    enabled: bool | None
    label: str | None
    capability: str | None = None


@dataclass(frozen=True)
class SafeFinding:
    """A diagnostic/health finding in safe, LLM-consumable form."""

    severity: str
    component: str
    title: str
    explanation: str
    recommendation: str
    evidence: str


@dataclass(frozen=True)
class SafeRecommendation:
    """A deterministic recommendation in LLM-consumable form.

    ``target`` and ``action`` are only present when the deterministic
    layer validated them. ``destructive`` tells the LLM this must remain
    a user-confirmed decision, never an automatic action.
    """

    severity: str
    title: str
    rationale: str
    action: str | None = None
    target: str | None = None
    destructive: bool = False


@dataclass(frozen=True)
class KillCandidate:
    """One deterministic "what could I close?" candidate.

    Produced by :mod:`android_task_manager.copilot.candidates` from
    deterministic signals (category, background state, resource usage,
    safety classification and action capability). The LLM explains this
    list; it never decides it.
    """

    name: str
    category: str
    safety: ProcessSafetyClass
    memory_percent: float | None
    cpu_percent: float | None
    reason: str
    estimated_reclaimable_kb: int | None = None


@dataclass(frozen=True)
class ProtectedProcess:
    """A process that must never be a kill candidate."""

    name: str
    safety: ProcessSafetyClass
    reason: str


@dataclass(frozen=True)
class CopilotContext:
    """Normalized, serializable device context. Controlled schema only."""

    device_label: str | None = None
    android_version: str | None = None
    device_model: str | None = None
    device_manufacturer: str | None = None
    uptime_seconds: float | None = None

    cpu_percent: float | None = None
    memory_used_percent: float | None = None
    memory_total_kb: int | None = None
    memory_available_kb: int | None = None
    battery_level_percent: float | None = None
    battery_status: str | None = None
    battery_temperature_c: float | None = None
    battery_health: str | None = None
    storage_used_percent: float | None = None
    storage_total_kb: int | None = None
    storage_available_kb: int | None = None
    network_connected: bool | None = None
    network_throughput_rx_bps: float | None = None
    network_throughput_tx_bps: float | None = None

    top_processes: tuple[SafeProcess, ...] = ()
    process_count: int | None = None
    installed_app_count: int | None = None
    user_app_count: int | None = None
    applications: tuple[SafeApp, ...] = ()

    health_status: str | None = None
    health_score: float | None = None
    health_findings: tuple[SafeFinding, ...] = ()
    diagnostics_findings: tuple[SafeFinding, ...] = ()
    recommendations: tuple[SafeRecommendation, ...] = ()

    performance_score: int | None = None
    performance_pressured: tuple[str, ...] = ()

    kill_candidates: tuple[KillCandidate, ...] = ()
    protected_processes: tuple[ProtectedProcess, ...] = ()

    intent: str | None = None
    current_page: str = "overview"
    connected: bool = False
    context_timestamp: float | None = None


@dataclass(frozen=True)
class CopilotMessage:
    """One message in the conversation."""

    role: CopilotRole
    content: str
    timestamp: float
    status: MessageStatus = MessageStatus.COMPLETE


@dataclass(frozen=True)
class CopilotResponse:
    """Parsed LLM response — structured output."""

    answer: str
    suggestions: tuple[str, ...] = ()
    confidence: str = "medium"
    related_pages: tuple[str, ...] = ()


@dataclass(frozen=True)
class CopilotRequest:
    """Full request payload sent to the worker."""

    query: str
    context: CopilotContext
    conversation_history: tuple[CopilotMessage, ...] = ()


@dataclass(frozen=True)
class CopilotResult:
    """Worker result — success or typed failure."""

    success: bool
    response: CopilotResponse | None = None
    error: str | None = None
    request_query: str = ""
