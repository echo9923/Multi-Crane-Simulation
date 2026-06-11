from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String enum base for stable YAML/OpenAPI values on Python 3.9."""


class LayoutMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class TaskAssignmentMode(StrEnum):
    PER_CRANE_QUEUE = "per_crane_queue"


class TaskGenerationMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class TaskType(StrEnum):
    EASY_TASK = "easy_task"
    OVERLAP_TASK = "overlap_task"
    STRESS_TASK = "stress_task"


class TaskRecoveryPolicy(StrEnum):
    ATTEMPT_SAFE_RELEASE = "attempt_safe_release"
    TERMINATE_EPISODE = "terminate_episode"


class QueueStartMode(StrEnum):
    SIMULTANEOUS = "simultaneous"
    STAGGERED = "staggered"
    SCHEDULED = "scheduled"


class WeatherMode(StrEnum):
    SCHEDULE = "schedule"
    CONSTANT = "constant"
    RANDOM = "random"


class RiskPromptMode(StrEnum):
    R0 = "R0"
    R1 = "R1"


class SafetyMode(StrEnum):
    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"


class RuntimeMode(StrEnum):
    OFFLINE_BATCH = "offline_batch"
    OFFLINE_REPLAY = "offline_replay"
    INTERACTIVE_SERVER = "interactive_server"


class LLMProviderName(StrEnum):
    DEEPSEEK = "deepseek"
    MINIMAX = "minimax"
    MOCK = "mock"
    REPLAY = "replay"


class OperatorProfile(StrEnum):
    NORMAL = "normal"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    NOVICE = "novice"
    FATIGUED = "fatigued"


class OverlapLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HeightStrategy(StrEnum):
    STAGGERED = "staggered"
    SAME_LEVEL = "same_level"
    MIXED = "mixed"


class CoverageTarget(StrEnum):
    BALANCED = "balanced"
    WIDE_COVERAGE = "wide_coverage"
    DENSE_OVERLAP = "dense_overlap"


class SlewMode(StrEnum):
    CONTINUOUS = "continuous"
    LIMITED = "limited"


class ForbiddenZonePolicyMode(StrEnum):
    TASK_ONLY = "task_only"
    HARD = "hard"


class PriorityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OperatorAssignmentMode(StrEnum):
    RANDOM = "random"
    MANUAL = "manual"
    PER_CRANE = "per_crane"


class LLMFallbackPolicy(StrEnum):
    NEUTRAL_STOP = "neutral_stop"


class LLMSchedulingMode(StrEnum):
    OFFLINE_WAIT = "offline_wait"
    REALTIME_STALE = "realtime_stale"


class StructuredOutputMode(StrEnum):
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


class LLMHistoryMode(StrEnum):
    NONE = "none"
    SHORT = "short"
    LONG = "long"


class SummarizerMode(StrEnum):
    NONE = "none"
    RULE = "rule"
    LLM = "llm"


class SummarizerProviderMode(StrEnum):
    SAME_AS_OPERATOR = "same_as_operator"
    EXPLICIT = "explicit"


class VisibilityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
