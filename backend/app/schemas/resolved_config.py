from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResolvedBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DefaultApplied(ResolvedBaseModel):
    field_path: str
    value: Any
    source: str
    reason: str


class ResolvedSeeds(ResolvedBaseModel):
    scenario: int
    experiment: int
    layout: int
    task: int
    weather: int
    operator_assignment: int


class ResolvedLayoutConfig(ResolvedBaseModel):
    mode: str
    auto_params: Optional[Dict[str, Any]] = None
    manual_cranes: Optional[List[Dict[str, Any]]] = None
    resolved_cranes: Optional[List[Dict[str, Any]]] = None
    layout_diagnostics: Optional[Dict[str, Any]] = None
    model_library_snapshot: Optional[Dict[str, Any]] = None


class ResolvedTaskConfig(ResolvedBaseModel):
    generation: Dict[str, Any]


class ResolvedOperatorsConfig(ResolvedBaseModel):
    assignment: Dict[str, Any]


class PersistedProviderSummary(ResolvedBaseModel):
    provider: str
    model: str
    base_url: Optional[str] = None
    temperature: float
    timeout_s: float
    max_retries: int
    key_source: str = "none"
    key_env_name: Optional[str] = None
    key_masked: Optional[str] = None


class ResolvedRuntimeConfig(ResolvedBaseModel):
    runtime: Dict[str, Any]
    sim: Dict[str, Any]
    risk_prompt_mode: str
    safety_mode: str


class ResolvedOutputConfig(ResolvedBaseModel):
    run_root: str = "runs"
    save_visual_frames: bool
    save_parquet: bool
    save_replay: bool


class ResolvedConfig(ResolvedBaseModel):
    schema_version: str
    scenario: Dict[str, Any]
    experiment: Dict[str, Any]
    dataset: Optional[Dict[str, Any]] = None
    defaults_applied: List[DefaultApplied] = Field(default_factory=list)
    seeds: ResolvedSeeds
    layout: ResolvedLayoutConfig
    tasks: ResolvedTaskConfig
    operators: ResolvedOperatorsConfig
    provider: PersistedProviderSummary
    runtime: ResolvedRuntimeConfig
    output: ResolvedOutputConfig
    resolved_config_hash: str
