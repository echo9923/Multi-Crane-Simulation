from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.recorder import SimFrame

API_SCHEMA_VERSION = "1.0"

M_E_CONFIG_INVALID = "M_E_CONFIG_INVALID"
M_E_EPISODE_NOT_FOUND = "M_E_EPISODE_NOT_FOUND"
M_E_INVALID_EPISODE_STATE = "M_E_INVALID_EPISODE_STATE"
M_E_EPISODE_START_FAILED = "M_E_EPISODE_START_FAILED"
M_E_RUNNER_FAILED = "M_E_RUNNER_FAILED"
M_E_SUMMARY_NOT_FOUND = "M_E_SUMMARY_NOT_FOUND"
M_E_DOWNLOAD_FAILED = "M_E_DOWNLOAD_FAILED"
M_E_DATASET_NOT_FOUND = "M_E_DATASET_NOT_FOUND"
M_E_DATASET_NOT_IMPLEMENTED = "M_E_DATASET_NOT_IMPLEMENTED"
M_E_WEBSOCKET_CLOSED = "M_E_WEBSOCKET_CLOSED"
M_E_INTERNAL = "M_E_INTERNAL"

API_ERROR_CODES = (
    M_E_CONFIG_INVALID,
    M_E_EPISODE_NOT_FOUND,
    M_E_INVALID_EPISODE_STATE,
    M_E_EPISODE_START_FAILED,
    M_E_RUNNER_FAILED,
    M_E_SUMMARY_NOT_FOUND,
    M_E_DOWNLOAD_FAILED,
    M_E_DATASET_NOT_FOUND,
    M_E_DATASET_NOT_IMPLEMENTED,
    M_E_WEBSOCKET_CLOSED,
    M_E_INTERNAL,
)

RunModeValue = Literal["offline_batch", "offline_replay", "interactive_server"]
RunnerValue = Literal["production", "local"]
SortOrder = Literal["asc", "desc"]


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        arbitrary_types_allowed=True,
    )


class ApiError(ApiBaseModel):
    schema_version: str = API_SCHEMA_VERSION
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiResponse(ApiBaseModel):
    code: Literal[0] = 0
    data: Any
    message: str = "ok"


class ApiErrorResponse(ApiBaseModel):
    code: str
    data: None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PaginationParams(ApiBaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class SortParams(ApiBaseModel):
    sort_by: Optional[str] = None
    sort_order: SortOrder = "asc"


class TimeRangeParams(ApiBaseModel):
    start_time_s: Optional[float] = Field(default=None, ge=0)
    end_time_s: Optional[float] = Field(default=None, ge=0)


class EpisodeFilterParams(ApiBaseModel):
    status: Optional[str] = None
    run_mode: Optional[RunModeValue] = None


class ScenarioValidateRequest(ApiBaseModel):
    config_path: Optional[str] = None
    scenario: Optional[dict[str, Any]] = None
    experiment: Optional[dict[str, Any]] = None
    dataset: Optional[dict[str, Any]] = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class ScenarioValidateResult(ApiBaseModel):
    valid: bool
    resolved_config_hash: Optional[str] = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[ApiError] = Field(default_factory=list)


class EpisodeStartRequest(ApiBaseModel):
    config_path: Optional[str] = None
    scenario: Optional[dict[str, Any]] = None
    experiment: Optional[dict[str, Any]] = None
    dataset: Optional[dict[str, Any]] = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    run_mode: Optional[RunModeValue] = None
    runner: Optional[RunnerValue] = None
    episode_id: Optional[str] = None
    autostart: bool = True


class EpisodeStartResponse(ApiBaseModel):
    episode_id: str
    run_id: Optional[str] = None
    run_dir: Optional[str] = None
    status: str
    resolved_config_hash: Optional[str] = None
    websocket_url: Optional[str] = None


class EpisodeControlResponse(ApiBaseModel):
    episode_id: str
    previous_status: str
    status: str
    accepted: bool
    reason: Optional[str] = None


class EpisodeStateResponse(ApiBaseModel):
    episode_id: str
    status: str
    frame_index: int = Field(ge=0)
    time_s: float = Field(ge=0)
    run_dir: Optional[str] = None
    last_frame: Optional[SimFrame] = None
    terminal_reason: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class EpisodeDownloadRequest(ApiBaseModel):
    include_logs: bool = True
    include_data: bool = True
    include_visual: bool = True


class DatasetListItem(ApiBaseModel):
    dataset_id: str
    path: str
    created_at: Optional[str] = None
    num_episodes: Optional[int] = Field(default=None, ge=0)
    summary_available: bool = False


class DatasetListResponse(ApiBaseModel):
    items: list[DatasetListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class DatasetSummaryResponse(ApiBaseModel):
    dataset_id: str
    summary: dict[str, Any]


__all__ = [
    "API_ERROR_CODES",
    "API_SCHEMA_VERSION",
    "M_E_CONFIG_INVALID",
    "M_E_DATASET_NOT_FOUND",
    "M_E_DATASET_NOT_IMPLEMENTED",
    "M_E_DOWNLOAD_FAILED",
    "M_E_EPISODE_NOT_FOUND",
    "M_E_EPISODE_START_FAILED",
    "M_E_INTERNAL",
    "M_E_INVALID_EPISODE_STATE",
    "M_E_RUNNER_FAILED",
    "M_E_SUMMARY_NOT_FOUND",
    "M_E_WEBSOCKET_CLOSED",
    "ApiBaseModel",
    "ApiError",
    "ApiErrorResponse",
    "ApiResponse",
    "DatasetListItem",
    "DatasetListResponse",
    "DatasetSummaryResponse",
    "EpisodeControlResponse",
    "EpisodeDownloadRequest",
    "EpisodeFilterParams",
    "EpisodeStartRequest",
    "EpisodeStartResponse",
    "EpisodeStateResponse",
    "PaginationParams",
    "ScenarioValidateRequest",
    "ScenarioValidateResult",
    "SortParams",
    "TimeRangeParams",
]
