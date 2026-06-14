from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.config import DatasetConfig

DATASET_SCHEMA_VERSION = "1.0"

DATASET_E_CONFIG_INVALID = "DATASET_E_CONFIG_INVALID"
DATASET_E_SOURCE_NOT_FOUND = "DATASET_E_SOURCE_NOT_FOUND"
DATASET_E_EPISODE_DISCOVERY_FAILED = "DATASET_E_EPISODE_DISCOVERY_FAILED"
DATASET_E_QUALITY_FAILED = "DATASET_E_QUALITY_FAILED"
DATASET_E_SPLIT_LEAKAGE = "DATASET_E_SPLIT_LEAKAGE"
DATASET_E_INSUFFICIENT_EPISODES = "DATASET_E_INSUFFICIENT_EPISODES"
DATASET_E_WINDOW_INDEX_FAILED = "DATASET_E_WINDOW_INDEX_FAILED"
DATASET_E_WRITE_FAILED = "DATASET_E_WRITE_FAILED"
DATASET_W_RISK_TARGET_MISSED = "DATASET_W_RISK_TARGET_MISSED"
DATASET_W_UNKNOWN_SCENARIO_CLASS = "DATASET_W_UNKNOWN_SCENARIO_CLASS"
DATASET_W_SHORT_EPISODE_INCLUDED = "DATASET_W_SHORT_EPISODE_INCLUDED"

DATASET_ERROR_CODES = (
    DATASET_E_CONFIG_INVALID,
    DATASET_E_SOURCE_NOT_FOUND,
    DATASET_E_EPISODE_DISCOVERY_FAILED,
    DATASET_E_QUALITY_FAILED,
    DATASET_E_SPLIT_LEAKAGE,
    DATASET_E_INSUFFICIENT_EPISODES,
    DATASET_E_WINDOW_INDEX_FAILED,
    DATASET_E_WRITE_FAILED,
)

DATASET_WARNING_CODES = (
    DATASET_W_RISK_TARGET_MISSED,
    DATASET_W_UNKNOWN_SCENARIO_CLASS,
    DATASET_W_SHORT_EPISODE_INCLUDED,
)

DatasetSplitName = Literal[
    "train",
    "val",
    "test",
    "test_seen_layout",
    "test_unseen_layout",
    "test_unseen_num_cranes",
    "test_high_risk",
]

CopyMode = Literal["copy", "symlink", "hardlink", "index_only"]
QualityStatus = Literal["passed", "warning", "failed"]

_SECRET_FIELD_PARTS = (
    "api_key",
    "authorization",
    "secret",
    "token",
    "password",
)
_ALLOWED_MASKED_SECRET_FIELDS = {
    "key_masked",
    "api_key_env",
    "key_source",
}


class DatasetBuildError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}


class DatasetBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        arbitrary_types_allowed=True,
    )


class DatasetBuildWarning(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    warning_code: str
    message: str
    episode_id: Optional[str] = None
    split: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class DatasetBuildOptions(DatasetBaseModel):
    source_roots: List[Path]
    output_root: Path
    max_episodes: Optional[int] = Field(default=None, gt=0)
    min_duration_s: Optional[float] = Field(default=300.0, ge=0)
    copy_mode: CopyMode = "index_only"
    fail_on_quality_error: bool = False
    include_quarantine_in_summary: bool = True

    @field_validator("source_roots")
    @classmethod
    def validate_source_roots(cls, value: List[Path]) -> List[Path]:
        if not value:
            raise ValueError("source_roots must not be empty")
        return value


class DatasetEpisodeRecord(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    experiment_id: Optional[str] = None
    run_dir: Path
    episode_status: str
    duration_s: float = Field(ge=0)
    frame_count: int = Field(ge=0)
    num_cranes: int = Field(ge=0)
    scenario_class: str = "unknown"
    layout_hash: Optional[str] = None
    resolved_config_hash: Optional[str] = None
    operator_profile_distribution: Dict[str, int] = Field(default_factory=dict)
    risk_frame_ratio_by_level: Dict[str, float] = Field(default_factory=dict)
    near_miss_count: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    source_files: Dict[str, Path] = Field(default_factory=dict)


class DatasetQualityReport(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    episode_id: str
    quality_status: QualityStatus
    failed_checks: List[str] = Field(default_factory=list)
    warnings: List[DatasetBuildWarning] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class DatasetSplitAssignment(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    episode_id: str
    split: DatasetSplitName
    reason: str
    holdout_flags: Dict[str, bool] = Field(default_factory=dict)


class DatasetSplitManifestAssignment(DatasetSplitAssignment):
    scenario_id: Optional[str] = None
    layout_hash: Optional[str] = None
    num_cranes: int = Field(ge=0)


class DatasetSplitManifest(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    split_strategy: str
    split_counts: Dict[str, int]
    assignments: List[DatasetSplitManifestAssignment]


class DatasetWindowIndexRow(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    split: DatasetSplitName
    episode_id: str
    scenario_id: Optional[str] = None
    start_frame: int = Field(ge=0)
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    stride_steps: int = Field(gt=0)
    input_start_time_s: float = Field(ge=0)
    prediction_end_time_s: float = Field(ge=0)
    num_cranes: int = Field(gt=0)
    label_horizons_s: List[float]
    source_paths: Dict[str, str]
    is_positive: bool = False

    @field_validator("label_horizons_s")
    @classmethod
    def validate_label_horizons(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("label_horizons_s must not be empty")
        if any(horizon <= 0 for horizon in value):
            raise ValueError("label_horizons_s values must be positive")
        return value


class DatasetFileRecord(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    episode_id: Optional[str] = None
    file_role: str
    path: str
    source_path: str
    checksum_sha256: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)
    copy_mode: CopyMode = "index_only"


class DatasetManifest(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    created_at: str
    git_commit: Optional[str] = None
    source_roots: List[str]
    copy_mode: CopyMode = "index_only"
    split_strategy: str
    window_config: Dict[str, Any]
    config: Dict[str, Any] = Field(default_factory=dict)
    files: List[DatasetFileRecord] = Field(default_factory=list)
    warnings: List[DatasetBuildWarning] = Field(default_factory=list)


class DatasetSummary(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    created_at: str
    git_commit: Optional[str] = None
    num_episodes: int = Field(ge=0)
    num_quarantined: int = Field(ge=0)
    split_counts: Dict[str, int]
    window_counts: Dict[str, int]
    risk_distribution: Dict[str, float]
    task_completion_rate: Optional[float] = Field(default=None, ge=0, le=1)
    near_miss_count: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    operator_profile_distribution: Dict[str, int] = Field(default_factory=dict)
    scenario_class_distribution: Dict[str, int] = Field(default_factory=dict)
    num_cranes_distribution: Dict[str, int] = Field(default_factory=dict)
    targets: Dict[str, Any] = Field(default_factory=dict)
    target_gaps: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[DatasetBuildWarning] = Field(default_factory=list)
    source_roots: List[str] = Field(default_factory=list)
    copy_mode: CopyMode = "index_only"


class DatasetBuildResult(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    dataset_dir: Path
    summary_path: Path
    manifest_path: Path
    split_manifest_path: Path
    window_index_path: Path
    num_episodes: int = Field(ge=0)
    num_quarantined: int = Field(ge=0)
    warnings: List[DatasetBuildWarning] = Field(default_factory=list)


class BatchEpisodeRequest(DatasetBaseModel):
    dataset_config: DatasetConfig
    output_root: Path
    max_episodes: Optional[int] = Field(default=None, gt=0)
    continue_on_episode_failure: bool = True


class BatchEpisodeResult(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    requested_episodes: int = Field(ge=0)
    completed_episodes: int = Field(ge=0)
    failed_episodes: int = Field(ge=0)
    run_dirs: List[Path]
    generation_report_path: Path
    failures: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[DatasetBuildWarning] = Field(default_factory=list)


def assert_no_secret_payload(payload: Any, *, context: str = "dataset") -> None:
    _scan_for_secret_payload(payload, path=context)


def _scan_for_secret_payload(payload: Any, *, path: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            field_path = f"{path}.{key_text}"
            if _is_forbidden_secret_field(key_text):
                raise DatasetBuildError(
                    DATASET_E_CONFIG_INVALID,
                    "dataset payload contains a secret-like field",
                    details={"field_path": field_path},
                )
            _scan_for_secret_payload(value, path=field_path)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            _scan_for_secret_payload(item, path=f"{path}[{index}]")


def _is_forbidden_secret_field(field_name: str) -> bool:
    normalized = field_name.lower()
    if normalized in _ALLOWED_MASKED_SECRET_FIELDS:
        return False
    return any(part in normalized for part in _SECRET_FIELD_PARTS)


__all__ = [
    "CopyMode",
    "DATASET_E_CONFIG_INVALID",
    "DATASET_E_EPISODE_DISCOVERY_FAILED",
    "DATASET_E_INSUFFICIENT_EPISODES",
    "DATASET_E_QUALITY_FAILED",
    "DATASET_E_SOURCE_NOT_FOUND",
    "DATASET_E_SPLIT_LEAKAGE",
    "DATASET_E_WINDOW_INDEX_FAILED",
    "DATASET_E_WRITE_FAILED",
    "DATASET_ERROR_CODES",
    "DATASET_SCHEMA_VERSION",
    "DATASET_WARNING_CODES",
    "DATASET_W_RISK_TARGET_MISSED",
    "DATASET_W_SHORT_EPISODE_INCLUDED",
    "DATASET_W_UNKNOWN_SCENARIO_CLASS",
    "DatasetBaseModel",
    "BatchEpisodeRequest",
    "BatchEpisodeResult",
    "DatasetBuildError",
    "DatasetBuildOptions",
    "DatasetBuildResult",
    "DatasetBuildWarning",
    "DatasetEpisodeRecord",
    "DatasetFileRecord",
    "DatasetManifest",
    "DatasetQualityReport",
    "DatasetSplitAssignment",
    "DatasetSplitManifest",
    "DatasetSplitManifestAssignment",
    "DatasetSplitName",
    "DatasetSummary",
    "DatasetWindowIndexRow",
    "QualityStatus",
    "assert_no_secret_payload",
]
