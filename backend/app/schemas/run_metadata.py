from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class RunMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    experiment_id: str
    scenario_id: str
    run_id: str
    created_at: str
    git_commit: Optional[str]
    git_dirty: Optional[bool]
    python_version: str
    package_summary: Dict[str, Any]
    resolved_config_hash: str
    provider: str
    model: str
    temperature: float
    key_source: str
    key_masked: Optional[str]
