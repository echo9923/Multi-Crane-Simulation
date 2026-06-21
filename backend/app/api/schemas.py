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
M_E_LLM_SETTINGS_INVALID = "M_E_LLM_SETTINGS_INVALID"
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
    M_E_LLM_SETTINGS_INVALID,
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
    manual_task_validation: Optional[dict[str, Any]] = None
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


class DesktopTemplate(ApiBaseModel):
    template_id: str
    name: str
    path: str
    scenario_id: Optional[str] = None
    experiment_id: Optional[str] = None
    description: Optional[str] = None


class DesktopTemplatesResponse(ApiBaseModel):
    items: list[DesktopTemplate]


class DesktopConfigRenderRequest(ApiBaseModel):
    template_id: str
    core_overrides: dict[str, Any] = Field(default_factory=dict)


class DesktopConfigPatchRequest(ApiBaseModel):
    yaml_text: str
    patches: dict[str, Any] = Field(default_factory=dict)


class DesktopConfigTextResponse(ApiBaseModel):
    yaml_text: str


class DesktopExperimentDraftRequest(ApiBaseModel):
    experiment_id: str
    yaml_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DesktopExperimentDraftResponse(ApiBaseModel):
    experiment_id: str
    yaml_path: str
    metadata_path: str


class DesktopExperimentDraftLatestResponse(ApiBaseModel):
    experiment_id: Optional[str] = None
    yaml_text: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    updated_at: Optional[str] = None


class DesktopRecentExperiment(ApiBaseModel):
    experiment_id: str
    yaml_path: str
    metadata_path: str
    template_id: Optional[str] = None
    last_validation_hash: Optional[str] = None
    updated_at: Optional[str] = None


class DesktopRecentExperimentsResponse(ApiBaseModel):
    items: list[DesktopRecentExperiment]


class DesktopRunItem(ApiBaseModel):
    episode_id: str
    path: str
    status: Optional[str] = None
    created_at: Optional[str] = None
    summary_available: bool


class DesktopRunsResponse(ApiBaseModel):
    items: list[DesktopRunItem]


class DesktopRunFile(ApiBaseModel):
    relative_path: str
    path: str
    size_bytes: int = Field(ge=0)
    kind: str


class DesktopRunFilesResponse(ApiBaseModel):
    episode_id: str
    files: list[DesktopRunFile]


class DesktopEnvironmentResponse(ApiBaseModel):
    project_root: str
    data_root: Optional[str] = None
    python_path: Optional[str] = None
    python_version: Optional[str] = None
    run_roots: list[str] = Field(default_factory=list)
    backend_port: Optional[int] = Field(default=None, ge=1, le=65535)


class DesktopLLMProviderSummary(ApiBaseModel):
    provider: str
    display_name: str
    default_base_url: Optional[str] = None
    default_model: str
    api_key_env: Optional[str] = None
    has_saved_key: bool
    key_masked: Optional[str] = None
    updated_at: Optional[str] = None


class DesktopLLMProvidersResponse(ApiBaseModel):
    items: list[DesktopLLMProviderSummary]


class DesktopLLMSecretSaveRequest(ApiBaseModel):
    api_key: str = Field(min_length=1)
    base_url: Optional[str] = None
    model: Optional[str] = None


class DesktopLLMConnectivityTestRequest(ApiBaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class DesktopLLMConnectivityTestResponse(ApiBaseModel):
    ok: bool
    provider: str
    base_url: str
    latency_ms: float = Field(ge=0)
    status_code: Optional[int] = None
    model_count: Optional[int] = Field(default=None, ge=0)
    sample_models: Optional[list[str]] = None
    message: Optional[str] = None


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
    "M_E_LLM_SETTINGS_INVALID",
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
    "DesktopConfigPatchRequest",
    "DesktopConfigRenderRequest",
    "DesktopConfigTextResponse",
    "DesktopEnvironmentResponse",
    "DesktopExperimentDraftRequest",
    "DesktopExperimentDraftLatestResponse",
    "DesktopExperimentDraftResponse",
    "DesktopLLMConnectivityTestRequest",
    "DesktopLLMConnectivityTestResponse",
    "DesktopLLMProviderSummary",
    "DesktopLLMProvidersResponse",
    "DesktopLLMSecretSaveRequest",
    "DesktopRecentExperiment",
    "DesktopRecentExperimentsResponse",
    "DesktopRunFile",
    "DesktopRunFilesResponse",
    "DesktopRunItem",
    "DesktopRunsResponse",
    "DesktopTemplate",
    "DesktopTemplatesResponse",
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
