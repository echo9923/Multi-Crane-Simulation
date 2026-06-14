from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TRAINING_SCHEMA_VERSION = "1.0"

TRAINING_E_CONFIG_INVALID = "TRAINING_E_CONFIG_INVALID"
TRAINING_E_MANIFEST_INVALID = "TRAINING_E_MANIFEST_INVALID"
TRAINING_E_WINDOWS_INVALID = "TRAINING_E_WINDOWS_INVALID"
TRAINING_E_SPLIT_LEAKAGE = "TRAINING_E_SPLIT_LEAKAGE"
TRAINING_E_SOURCE_MISSING = "TRAINING_E_SOURCE_MISSING"
TRAINING_E_SOURCE_SCHEMA_INVALID = "TRAINING_E_SOURCE_SCHEMA_INVALID"
TRAINING_E_TIME_AXIS_INVALID = "TRAINING_E_TIME_AXIS_INVALID"
TRAINING_E_TIME_LEAKAGE = "TRAINING_E_TIME_LEAKAGE"
TRAINING_E_LABEL_MISSING = "TRAINING_E_LABEL_MISSING"
TRAINING_E_VARIABLE_NODES_UNSUPPORTED = "TRAINING_E_VARIABLE_NODES_UNSUPPORTED"
TRAINING_E_SECRET_LEAKAGE = "TRAINING_E_SECRET_LEAKAGE"
TRAINING_E_WRITE_FAILED = "TRAINING_E_WRITE_FAILED"
TRAINING_W_INDEX_ONLY_RISK_LABEL_MISSING = "TRAINING_W_INDEX_ONLY_RISK_LABEL_MISSING"

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
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9._-]*"),
    re.compile(r"(?i)authorization:\s*bearer\s+[^\s,;]+"),
    re.compile(r"(?i)([?&](?:token|api_key|secret|password)=)[^&#\s]+"),
)

DEFAULT_NODE_FEATURES = (
    "theta_sin",
    "theta_cos",
    "theta_dot_rad_s",
    "trolley_r_m",
    "trolley_v_m_s",
    "hook_h_m",
    "hoist_v_m_s",
    "root_x",
    "root_y",
    "root_z",
    "tip_x",
    "tip_y",
    "tip_z",
    "hook_x",
    "hook_y",
    "hook_z",
    "load_attached",
    "load_weight_t",
    "task_stage_code",
    "has_task",
    "wind_speed_m_s",
    "wind_gust_m_s",
    "wind_direction_sin",
    "wind_direction_cos",
    "visibility_code",
)
DEFAULT_EDGE_FEATURES = (
    "edge_distance_m",
    "edge_overlap_ratio",
    "edge_delta_height_m",
    "edge_delta_theta_rad",
    "edge_delta_theta_dot_rad_s",
    "clearance_min_now_m",
    "risk_level_now_code",
)
DEFAULT_TRAJ_TARGETS = (
    "theta_sin",
    "theta_cos",
    "trolley_r_m",
    "hook_h_m",
    "hook_x",
    "hook_y",
    "hook_z",
)
DEFAULT_RISK_TARGETS = (
    "risk_level_code",
    "collision_label",
    "min_clearance_future_m",
    "ttc_s",
)


class TrainingConversionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = _sanitize_string(message)
        self.details = sanitize_training_payload(details or {})
        super().__init__(f"{self.code}: {self.message} details={self.details}")


class TrainingBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        arbitrary_types_allowed=True,
    )


class StgnnFeatureSpec(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    node_features: List[str]
    edge_features: List[str]
    traj_targets: List[str]
    risk_targets: List[str]
    risk_label_horizons_s: List[float]
    variable_node_strategy: Literal["pad_and_mask"] = "pad_and_mask"
    max_nodes: int = Field(gt=0)

    @field_validator(
        "node_features",
        "edge_features",
        "traj_targets",
        "risk_targets",
    )
    @classmethod
    def validate_non_empty_strings(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("feature lists must not be empty")
        if any(not item for item in value):
            raise ValueError("feature names must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("feature names must be unique")
        return value

    @field_validator("risk_label_horizons_s")
    @classmethod
    def validate_horizons(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("risk_label_horizons_s must not be empty")
        normalized: list[float] = []
        for horizon in value:
            if not math.isfinite(horizon) or horizon <= 0:
                raise ValueError("risk label horizons must be positive finite values")
            normalized.append(float(horizon))
        return sorted(set(normalized))


class StgnnConversionOptions(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    dataset_root: Path
    output_root: Optional[Path] = None
    strict: bool = True
    splits: Optional[List[str]] = None
    max_nodes: Optional[int] = Field(default=None, gt=0)
    dry_run: bool = False
    write_npz: bool = False
    allow_graph_edge_fallback: bool = False

    @field_validator("splits")
    @classmethod
    def validate_splits(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if not value:
            raise ValueError("splits must not be empty when provided")
        if any(not split for split in value):
            raise ValueError("split names must not be empty")
        return value


class StgnnSampleMetadata(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    dataset_id: str
    split: str
    scenario_id: Optional[str] = None
    episode_id: str
    start_frame: int = Field(ge=0)
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    stride_steps: int = Field(gt=0)
    risk_label_horizons_s: List[float]
    source_paths: Dict[str, str]
    source_window_index: Dict[str, Any]
    feature_spec_hash: str

    @field_validator("risk_label_horizons_s")
    @classmethod
    def validate_horizons(cls, value: List[float]) -> List[float]:
        return StgnnFeatureSpec.validate_horizons(value)

    @model_validator(mode="after")
    def validate_metadata_payload(self) -> "StgnnSampleMetadata":
        assert_no_training_secret(self.source_paths, context="sample_source_paths")
        assert_no_training_secret(
            self.source_window_index,
            context="source_window_index",
        )
        return self


class StgnnSampleIndexRow(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    sample_id: str
    dataset_id: str
    split: str
    episode_id: str
    scenario_id: Optional[str] = None
    start_frame: int = Field(ge=0)
    tensor_path: Optional[str] = None
    tensor_offset: Optional[int] = Field(default=None, ge=0)
    num_nodes: int = Field(gt=0)
    max_nodes: int = Field(gt=0)
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    node_feature_dim: int = Field(gt=0)
    edge_feature_dim: int = Field(gt=0)
    traj_target_dim: int = Field(gt=0)
    risk_target_dim: int = Field(gt=0)
    metadata_json: Dict[str, Any]

    @model_validator(mode="after")
    def validate_node_bounds(self) -> "StgnnSampleIndexRow":
        if self.num_nodes > self.max_nodes:
            raise ValueError("num_nodes must be <= max_nodes")
        assert_no_training_secret(self.metadata_json, context="sample_index_metadata")
        return self


class StgnnTensorSample(TrainingBaseModel):
    metadata: StgnnSampleMetadata
    feature_spec: StgnnFeatureSpec
    X_node: np.ndarray
    X_edge: np.ndarray
    A_phy: np.ndarray
    Y_traj: np.ndarray
    Y_risk: np.ndarray
    node_mask: np.ndarray
    edge_mask: np.ndarray
    risk_mask: np.ndarray

    @model_validator(mode="after")
    def validate_shapes(self) -> "StgnnTensorSample":
        input_steps = self.metadata.input_steps
        pred_steps = self.metadata.pred_steps
        max_nodes = self.feature_spec.max_nodes
        horizons = len(self.feature_spec.risk_label_horizons_s)
        expected_shapes = {
            "X_node": (input_steps, max_nodes, len(self.feature_spec.node_features)),
            "X_edge": (
                input_steps,
                max_nodes,
                max_nodes,
                len(self.feature_spec.edge_features),
            ),
            "A_phy": (input_steps, max_nodes, max_nodes),
            "Y_traj": (pred_steps, max_nodes, len(self.feature_spec.traj_targets)),
            "Y_risk": (
                horizons,
                max_nodes,
                max_nodes,
                len(self.feature_spec.risk_targets),
            ),
            "node_mask": (max_nodes,),
            "edge_mask": (max_nodes, max_nodes),
            "risk_mask": (horizons, max_nodes, max_nodes),
        }
        for field_name, expected in expected_shapes.items():
            actual = getattr(self, field_name).shape
            if actual != expected:
                raise ValueError(
                    f"{field_name} shape must be {expected}, got {actual}"
                )
        if self.metadata.risk_label_horizons_s != self.feature_spec.risk_label_horizons_s:
            raise ValueError("metadata and feature spec risk horizons must match")
        _assert_finite_array(self.X_node, "X_node")
        _assert_finite_array(self.X_edge, "X_edge")
        _assert_finite_array(self.A_phy, "A_phy")
        _assert_finite_array(self.Y_traj, "Y_traj")
        _assert_finite_array(self.Y_risk, "Y_risk")
        return self


class StgnnManifest(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    dataset_id: str
    source_dataset_root: str
    output_root: str
    feature_spec: StgnnFeatureSpec
    sample_index_path: Optional[str] = None
    summary_path: Optional[str] = None
    warnings: List[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest_secrets(self) -> "StgnnManifest":
        assert_no_training_secret(self.model_dump(mode="json"), context="stgnn_manifest")
        return self


class StgnnConversionSummary(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    dataset_id: str
    sample_counts: Dict[str, int]
    skipped_counts: Dict[str, int] = Field(default_factory=dict)
    num_episodes: int = Field(ge=0)
    max_nodes: int = Field(gt=0)
    feature_spec: StgnnFeatureSpec
    risk_distribution: Dict[str, float] = Field(default_factory=dict)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("sample_counts", "skipped_counts")
    @classmethod
    def validate_counts(cls, value: Dict[str, int]) -> Dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("counts must be non-negative")
        return value

    @field_validator("risk_distribution")
    @classmethod
    def validate_distribution(cls, value: Dict[str, float]) -> Dict[str, float]:
        if any(not math.isfinite(ratio) or ratio < 0 for ratio in value.values()):
            raise ValueError("risk distribution values must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def validate_summary_secrets(self) -> "StgnnConversionSummary":
        assert_no_training_secret(self.warnings, context="stgnn_summary_warnings")
        return self


class StgnnConversionResult(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    manifest: StgnnManifest
    summary: StgnnConversionSummary
    samples: List[StgnnSampleIndexRow] = Field(default_factory=list)


def default_stgnn_feature_spec(
    *,
    max_nodes: int,
    risk_label_horizons_s: List[float],
) -> StgnnFeatureSpec:
    return StgnnFeatureSpec(
        node_features=list(DEFAULT_NODE_FEATURES),
        edge_features=list(DEFAULT_EDGE_FEATURES),
        traj_targets=list(DEFAULT_TRAJ_TARGETS),
        risk_targets=list(DEFAULT_RISK_TARGETS),
        risk_label_horizons_s=risk_label_horizons_s,
        max_nodes=max_nodes,
    )


def feature_spec_hash(spec: StgnnFeatureSpec) -> str:
    payload = json.dumps(
        spec.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_no_training_secret(payload: Any, *, context: str = "training") -> None:
    issue = _find_secret_issue(payload)
    if issue is None:
        return
    raise TrainingConversionError(
        TRAINING_E_SECRET_LEAKAGE,
        f"secret-like payload rejected in {context}",
        details=issue,
    )


def sanitize_training_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[Any, Any] = {}
        for key, value in payload.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_training_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_training_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(sanitize_training_payload(item) for item in payload)
    if isinstance(payload, str):
        return _sanitize_string(payload)
    return payload


def _find_secret_issue(payload: Any, *, path: str = "$") -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            field_path = f"{path}.{key_text}"
            if _is_secret_key(key_text):
                return {"field_path": field_path, "reason": "secret-like key"}
            issue = _find_secret_issue(value, path=field_path)
            if issue is not None:
                return issue
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            issue = _find_secret_issue(item, path=f"{path}[{index}]")
            if issue is not None:
                return issue
    elif isinstance(payload, str):
        if _sanitize_string(payload) != payload:
            return {"field_path": path, "reason": "secret-like value"}
    return None


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _ALLOWED_MASKED_SECRET_FIELDS:
        return False
    return any(part in lowered for part in _SECRET_FIELD_PARTS)


def _sanitize_string(value: str) -> str:
    sanitized = value
    for pattern in _SECRET_VALUE_PATTERNS:
        sanitized = pattern.sub(_replace_secret_match, sanitized)
    return sanitized


def _replace_secret_match(match: re.Match[str]) -> str:
    if match.re.pattern.startswith("(?i)([?&]"):
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def _assert_finite_array(array: np.ndarray, field_name: str) -> None:
    if array.dtype.kind in {"f", "c"} and not np.isfinite(array).all():
        raise ValueError(f"{field_name} must not contain NaN or Inf")


__all__ = [
    "TRAINING_SCHEMA_VERSION",
    "TRAINING_E_CONFIG_INVALID",
    "TRAINING_E_MANIFEST_INVALID",
    "TRAINING_E_WINDOWS_INVALID",
    "TRAINING_E_SPLIT_LEAKAGE",
    "TRAINING_E_SOURCE_MISSING",
    "TRAINING_E_SOURCE_SCHEMA_INVALID",
    "TRAINING_E_TIME_AXIS_INVALID",
    "TRAINING_E_TIME_LEAKAGE",
    "TRAINING_E_LABEL_MISSING",
    "TRAINING_E_VARIABLE_NODES_UNSUPPORTED",
    "TRAINING_E_SECRET_LEAKAGE",
    "TRAINING_E_WRITE_FAILED",
    "TRAINING_W_INDEX_ONLY_RISK_LABEL_MISSING",
    "TrainingConversionError",
    "TrainingBaseModel",
    "StgnnFeatureSpec",
    "StgnnConversionOptions",
    "StgnnSampleMetadata",
    "StgnnSampleIndexRow",
    "StgnnTensorSample",
    "StgnnManifest",
    "StgnnConversionSummary",
    "StgnnConversionResult",
    "default_stgnn_feature_spec",
    "feature_spec_hash",
    "assert_no_training_secret",
    "sanitize_training_payload",
]
