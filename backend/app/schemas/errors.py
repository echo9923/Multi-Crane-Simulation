from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class ConfigError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    error_code: str
    severity: str = "E"
    category: str = "startup_error"
    message: str
    field_path: Optional[str]
    source_file: Optional[str]
    hint: str
    details: Dict[str, Any]


class StartupFailureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_start: bool = False
    errors: List[ConfigError]
