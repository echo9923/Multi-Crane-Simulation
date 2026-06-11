from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any, Dict, List

from pydantic import ValidationError

from backend.app.schemas.command import (
    CommandValidationError,
    ParsedCommand,
    RawLLMResponse,
)


class CommandParseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        errors: List[CommandValidationError],
    ) -> None:
        self.errors = errors
        super().__init__(message)


def extract_json_object(content: str) -> Dict[str, Any]:
    stripped = content.strip()
    if not stripped:
        raise _parse_error("LLM response content is empty", raw_fragment=content)
    try:
        parsed = json.loads(stripped)
    except JSONDecodeError as exc:
        raise _parse_error(
            f"LLM response must be a single JSON object: {exc.msg}",
            raw_fragment=content,
        ) from exc
    if not isinstance(parsed, dict):
        raise _parse_error("LLM response JSON must be an object", raw_fragment=content)
    return parsed


def parse_raw_llm_response(
    raw_response: RawLLMResponse,
    *,
    command_duration_min_s: float,
    command_duration_max_s: float,
) -> ParsedCommand:
    payload = extract_json_object(raw_response.content)
    payload = _with_authoritative_metadata(raw_response, payload)
    try:
        parsed = ParsedCommand.model_validate(payload)
    except ValidationError as exc:
        raise CommandParseError(
            "LLM response failed command schema validation",
            errors=validation_errors_from_exception(exc),
        ) from exc
    if not (
        command_duration_min_s
        <= parsed.command_duration_s
        <= command_duration_max_s
    ):
        raise CommandParseError(
            "LLM command_duration_s is outside configured bounds",
            errors=[
                CommandValidationError(
                    error_code="LLM_E_002",
                    field_path="command_duration_s",
                    message=(
                        "command_duration_s must be between "
                        f"{command_duration_min_s} and {command_duration_max_s}"
                    ),
                    raw_fragment=str(parsed.command_duration_s),
                    retryable=True,
                )
            ],
        )
    return parsed


def validation_errors_from_exception(exc: Exception) -> List[CommandValidationError]:
    if isinstance(exc, CommandParseError):
        return exc.errors
    if isinstance(exc, ValidationError):
        return [
            CommandValidationError(
                error_code="LLM_E_002",
                field_path=_format_loc(error.get("loc", ())),
                message=str(error.get("msg", "validation error")),
                raw_fragment=_format_input(error.get("input")),
                retryable=True,
            )
            for error in exc.errors()
        ]
    return [
        CommandValidationError(
            error_code="LLM_E_002",
            message=str(exc),
            retryable=True,
        )
    ]


def _with_authoritative_metadata(
    raw_response: RawLLMResponse,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    command_payload = dict(payload)
    for key in [
        "schema_version",
        "command_id",
        "response_id",
        "observation_id",
        "source_snapshot_id",
        "operator_id",
        "crane_id",
        "time_s",
    ]:
        command_payload.pop(key, None)
    command_payload.update(
        {
            "command_id": f"cmd-{raw_response.response_id}",
            "response_id": raw_response.response_id,
            "observation_id": raw_response.observation_id,
            "source_snapshot_id": raw_response.source_snapshot_id,
            "operator_id": raw_response.operator_id,
            "crane_id": raw_response.crane_id,
            "time_s": raw_response.time_s,
        }
    )
    return command_payload


def _parse_error(
    message: str,
    *,
    raw_fragment: str,
) -> CommandParseError:
    return CommandParseError(
        message,
        errors=[
            CommandValidationError(
                error_code="LLM_E_002",
                message=message,
                raw_fragment=raw_fragment,
                retryable=True,
            )
        ],
    )


def _format_loc(loc: object) -> str:
    if isinstance(loc, tuple):
        return ".".join(str(part) for part in loc)
    if isinstance(loc, list):
        return ".".join(str(part) for part in loc)
    return str(loc) if loc else ""


def _format_input(value: Any) -> str:
    if value is None:
        return "null"
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)
