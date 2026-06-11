from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.enums import LLMProviderName, OperatorProfile
from backend.app.schemas.observation import Observation

COMMAND_SCHEMA_VERSION = "1.0"

FORBIDDEN_COMMAND_SECRET_FIELDS = {
    "api_key",
    "resolved_full_api_key",
    "raw_api_key",
    "secret",
    "token",
    "authorization",
}


class CommandBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TokenUsage(CommandBaseModel):
    prompt_tokens: Optional[int] = Field(default=None, ge=0)
    completion_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)


class LLMMessage(CommandBaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def reject_secret_markers(cls, value: str) -> str:
        lowered = value.lower()
        for field_name in FORBIDDEN_COMMAND_SECRET_FIELDS:
            if field_name in lowered:
                raise ValueError(f"forbidden secret marker in message: {field_name}")
        return value


class AxisCommand(CommandBaseModel):
    direction: str
    gear: int = Field(ge=0, le=5)

    @model_validator(mode="after")
    def validate_direction_and_gear(self) -> "AxisCommand":
        if self.direction == "neutral" and self.gear != 0:
            raise ValueError("neutral direction requires gear 0")
        if self.direction != "neutral" and self.gear == 0:
            raise ValueError("gear 0 requires neutral direction")
        return self


class SlewAxisCommand(AxisCommand):
    direction: Literal["left", "neutral", "right"]


class TrolleyAxisCommand(AxisCommand):
    direction: Literal["in", "neutral", "out"]


class HoistAxisCommand(AxisCommand):
    direction: Literal["up", "neutral", "down"]


class LeftJoystickCommand(CommandBaseModel):
    slew: SlewAxisCommand
    trolley: TrolleyAxisCommand


class RightJoystickCommand(CommandBaseModel):
    hoist: HoistAxisCommand


class CommandValidationError(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    error_code: str
    message: str
    field_path: Optional[str] = None
    raw_fragment: Optional[str] = None
    retryable: bool = True


class RawLLMResponse(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    response_id: str
    provider: LLMProviderName
    model: str
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float = Field(ge=0)
    content: str
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: Optional[float] = Field(default=None, ge=0)
    token_usage: Optional[TokenUsage] = None

    @field_validator("raw_payload")
    @classmethod
    def reject_secret_fields(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        offending_path = _find_forbidden_secret_field(value)
        if offending_path is not None:
            raise ValueError(f"forbidden secret field: {offending_path}")
        return value


class ParsedCommand(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    command_id: str
    response_id: Optional[str] = None
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float = Field(ge=0)
    left_joystick: LeftJoystickCommand
    right_joystick: RightJoystickCommand
    deadman_pressed: bool
    emergency_stop: bool
    horn: bool
    command_duration_s: float = Field(ge=0.5, le=3.0)
    task_action: Literal["none", "request_attach", "request_release"]
    attention_target: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    fallback_reason: Optional[str] = None


class LLMCallRecord(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    call_id: str
    observation: Observation
    messages: List[LLMMessage]
    raw_response: Optional[RawLLMResponse]
    parsed_command: Optional[ParsedCommand]
    validation_errors: List[CommandValidationError]
    provider: LLMProviderName
    model: str
    latency_ms: Optional[float] = Field(default=None, ge=0)
    token_usage: Optional[TokenUsage]
    attempt_index: int = Field(ge=0)


class OperatorSession(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    operator_id: str
    crane_id: str
    profile: OperatorProfile
    consecutive_failures: int = Field(default=0, ge=0)
    decision_index: int = Field(default=0, ge=0)
    history: List[LLMMessage] = Field(default_factory=list)


class OperatorDecisionResult(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    observation: Observation
    parsed_command: ParsedCommand
    call_records: List[LLMCallRecord]
    validation_errors: List[CommandValidationError] = Field(default_factory=list)
    provider: LLMProviderName
    model: str
    fallback_applied: bool = False
    episode_failure_reason: Optional[Literal["llm_failed"]] = None


def build_neutral_stop_command(
    *,
    observation_id: str,
    source_snapshot_id: str,
    operator_id: str,
    crane_id: str,
    time_s: float,
    command_id: str,
    response_id: Optional[str] = None,
    command_duration_s: float = 1.0,
    reason: str,
) -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        response_id=response_id,
        observation_id=observation_id,
        source_snapshot_id=source_snapshot_id,
        operator_id=operator_id,
        crane_id=crane_id,
        time_s=time_s,
        left_joystick=LeftJoystickCommand(
            slew=SlewAxisCommand(direction="neutral", gear=0),
            trolley=TrolleyAxisCommand(direction="neutral", gear=0),
        ),
        right_joystick=RightJoystickCommand(
            hoist=HoistAxisCommand(direction="neutral", gear=0)
        ),
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=command_duration_s,
        task_action="none",
        attention_target="fallback_neutral_stop",
        confidence=0.0,
        reason=reason,
        fallback_reason=reason,
    )


def _find_forbidden_secret_field(payload: Any, path: str = "") -> Optional[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            current_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_COMMAND_SECRET_FIELDS:
                return current_path
            found = _find_forbidden_secret_field(value, current_path)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found = _find_forbidden_secret_field(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None
