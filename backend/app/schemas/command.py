from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.enums import LLMProviderName, OperatorProfile
from backend.app.schemas.observation import Observation
from backend.app.schemas.risk import (
    ForbiddenZoneResult,
    InterventionRecord,
    MechanicalLimitResult,
    SAFETY_SCHEMA_VERSION,
)

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


class ExecutedAxisCommand(CommandBaseModel):
    direction: str
    gear: int = Field(ge=0, le=5)
    speed_scale: float = Field(default=1.0, ge=0, le=1)
    source: Literal["raw", "mechanical_limit", "forbidden_zone", "risk_intervention"]

    @model_validator(mode="after")
    def validate_direction_and_gear(self) -> "ExecutedAxisCommand":
        if self.direction == "neutral" and self.gear != 0:
            raise ValueError("neutral direction requires gear 0")
        if self.direction != "neutral" and self.gear == 0:
            raise ValueError("gear 0 requires neutral direction")
        return self


class ExecutedLeftJoystickCommand(CommandBaseModel):
    slew: ExecutedAxisCommand
    trolley: ExecutedAxisCommand


class ExecutedRightJoystickCommand(CommandBaseModel):
    hoist: ExecutedAxisCommand


class ExecutedCommand(CommandBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    command_id: str
    raw_command_id: str
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float = Field(ge=0)
    raw_command: ParsedCommand
    left_joystick: ExecutedLeftJoystickCommand
    right_joystick: ExecutedRightJoystickCommand
    deadman_pressed: bool
    emergency_stop: bool
    horn: bool
    command_duration_s: float = Field(ge=0)
    task_action: Literal["none", "request_attach", "request_release"]
    modified: bool
    modification_reasons: List[str] = Field(default_factory=list)
    mechanical_limit: Optional[MechanicalLimitResult] = None
    forbidden_zone: Optional[ForbiddenZoneResult] = None
    interventions: List[InterventionRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_modification_contract(self) -> "ExecutedCommand":
        if self.modified and not self.modification_reasons:
            raise ValueError("modified executed command requires modification reasons")
        if not self.modified and self.modification_reasons:
            raise ValueError("unmodified executed command must not include reasons")
        if self.raw_command_id != self.raw_command.command_id:
            raise ValueError("raw_command_id must match raw_command.command_id")
        return self

    @classmethod
    def from_raw(
        cls,
        *,
        command_id: str,
        raw_command: ParsedCommand,
        mechanical_limit: Optional[MechanicalLimitResult] = None,
        forbidden_zone: Optional[ForbiddenZoneResult] = None,
        interventions: Optional[List[InterventionRecord]] = None,
        modification_reasons: Optional[List[str]] = None,
    ) -> "ExecutedCommand":
        reasons = list(modification_reasons or [])
        all_interventions = list(interventions or [])
        modified = bool(
            reasons
            or (mechanical_limit and mechanical_limit.modified)
            or (forbidden_zone and forbidden_zone.blocked)
            or any(intervention.modified for intervention in all_interventions)
        )
        return cls(
            command_id=command_id,
            raw_command_id=raw_command.command_id,
            observation_id=raw_command.observation_id,
            source_snapshot_id=raw_command.source_snapshot_id,
            operator_id=raw_command.operator_id,
            crane_id=raw_command.crane_id,
            time_s=raw_command.time_s,
            raw_command=raw_command,
            left_joystick=ExecutedLeftJoystickCommand(
                slew=ExecutedAxisCommand(
                    direction=raw_command.left_joystick.slew.direction,
                    gear=raw_command.left_joystick.slew.gear,
                    source="raw",
                ),
                trolley=ExecutedAxisCommand(
                    direction=raw_command.left_joystick.trolley.direction,
                    gear=raw_command.left_joystick.trolley.gear,
                    source="raw",
                ),
            ),
            right_joystick=ExecutedRightJoystickCommand(
                hoist=ExecutedAxisCommand(
                    direction=raw_command.right_joystick.hoist.direction,
                    gear=raw_command.right_joystick.hoist.gear,
                    source="raw",
                )
            ),
            deadman_pressed=raw_command.deadman_pressed,
            emergency_stop=raw_command.emergency_stop,
            horn=raw_command.horn,
            command_duration_s=raw_command.command_duration_s,
            task_action=raw_command.task_action,
            modified=modified,
            modification_reasons=reasons,
            mechanical_limit=mechanical_limit,
            forbidden_zone=forbidden_zone,
            interventions=all_interventions,
        )


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
