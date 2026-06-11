from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.enums import StrEnum

TASK_SCHEMA_VERSION = "1.0"


class TaskBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskStage(StrEnum):
    IDLE = "idle"
    MOVE_TO_PICKUP = "move_to_pickup"
    ALIGN_PICKUP = "align_pickup"
    LOWER_FOR_ATTACH = "lower_for_attach"
    ATTACH_PENDING = "attach_pending"
    LIFT_LOAD = "lift_load"
    MOVE_TO_DROPOFF = "move_to_dropoff"
    ALIGN_DROPOFF = "align_dropoff"
    LOWER_FOR_RELEASE = "lower_for_release"
    RELEASE_PENDING = "release_pending"
    RECOVERY_RELEASE = "recovery_release"


class TaskPoint(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    x: float
    y: float
    z: float
    zone_id: str
    zone_type: Literal["material", "work", "recovery"]

    def as_xyz(self) -> List[float]:
        return [self.x, self.y, self.z]


class Task(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    task_id: str
    crane_id: str
    task_type: Literal["easy_task", "overlap_task", "stress_task", "recovery_release"]
    pickup: TaskPoint
    dropoff: TaskPoint
    pickup_zone_id: str
    dropoff_zone_id: str
    planned_start_s: Optional[float] = None
    load_type: str
    load_weight_t: float = Field(gt=0)
    load_size_m: List[float]
    priority: Literal["low", "medium", "high"] = "medium"
    deadline_s: Optional[float] = Field(default=None, gt=0)
    deadline_missed: bool = False
    overtime_s: float = Field(default=0.0, ge=0)
    status: Literal["pending", "active", "completed", "failed", "skipped"] = "pending"
    started_at_s: Optional[float] = None
    completed_at_s: Optional[float] = None
    failed_at_s: Optional[float] = None
    failure_reason: Optional[str] = None
    source_failed_task_id: Optional[str] = None
    generation_seed: int
    generation_attempt: int = Field(ge=0)

    @field_validator("load_size_m")
    @classmethod
    def validate_load_size(cls, value: List[float]) -> List[float]:
        if len(value) != 3:
            raise ValueError("load_size_m must contain exactly three values")
        if any(component <= 0 for component in value):
            raise ValueError("load_size_m values must be positive")
        return value


class TaskQueue(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    crane_id: str
    tasks: List[Task] = Field(default_factory=list)
    active_task_id: Optional[str] = None
    next_task_index: int = Field(default=0, ge=0)
    last_completed_task_id: Optional[str] = None
    ready_after_s: float = Field(default=0.0, ge=0)
    blocked_by_recovery: bool = False


class TaskGenerationReport(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    seed: int
    num_cranes: int = Field(ge=0)
    num_tasks_total: int = Field(ge=0)
    num_tasks_by_type: Dict[str, int]
    num_resample_attempts: int = Field(default=0, ge=0)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)
    blocking_errors: List[Dict[str, Any]] = Field(default_factory=list)


class TaskRuntimeDiagnostic(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    time_s: float
    crane_id: str
    task_id: Optional[str] = None
    task_stage: Optional[str] = None
    reason: str
    details: Dict[str, Any] = Field(default_factory=dict)


class TaskActionSignal(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    crane_id: str
    command_id: Optional[str] = None
    time_s: float
    task_action: Literal["none", "request_attach", "request_release"] = "none"
    motion_is_non_neutral: bool = False


class TaskEventPayload(TaskBaseModel):
    schema_version: str = TASK_SCHEMA_VERSION
    event_type: str
    time_s: float
    frame_index: Optional[int] = None
    crane_id: str
    task_id: Optional[str] = None
    task_type: Optional[str] = None
    task_status: Optional[str] = None
    task_stage: Optional[str] = None
    reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
