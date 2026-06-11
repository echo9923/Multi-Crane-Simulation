from __future__ import annotations

import json

import pytest

from backend.app.schemas.command import CommandValidationError, RawLLMResponse
from backend.app.schemas.enums import LLMProviderName
from backend.app.sim.command_parser import (
    CommandParseError,
    extract_json_object,
    parse_raw_llm_response,
    validation_errors_from_exception,
)


def _raw_response(content: str, *, response_id: str = "resp-001") -> RawLLMResponse:
    return RawLLMResponse(
        response_id=response_id,
        provider=LLMProviderName.MOCK,
        model="mock-command-v1",
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        content=content,
    )


def _payload(**overrides) -> dict:
    payload = {
        "left_joystick": {
            "slew": {"direction": "left", "gear": 2},
            "trolley": {"direction": "out", "gear": 1},
        },
        "right_joystick": {"hoist": {"direction": "neutral", "gear": 0}},
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": False,
        "command_duration_s": 1.0,
        "task_action": "none",
        "attention_target": "pickup_area",
        "confidence": 0.76,
        "reason": "valid command",
        "schema_version": "model-forged-schema",
        "command_id": "model-forged-command",
        "response_id": "model-forged-response",
        "observation_id": "model-forged-observation",
        "source_snapshot_id": "model-forged-snapshot",
        "operator_id": "model-forged-operator",
        "crane_id": "model-forged-crane",
        "time_s": 999.0,
    }
    payload.update(overrides)
    return payload


def _content(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_extract_json_object_reports_original_fragment_for_malformed_content() -> None:
    content = "prefix {bad json"

    with pytest.raises(CommandParseError) as exc_info:
        extract_json_object(content)

    assert exc_info.value.errors[0].raw_fragment == content
    assert "single JSON object" in exc_info.value.errors[0].message


def test_parse_validation_error_field_path_includes_nested_extra_field() -> None:
    payload = _payload()
    payload["left_joystick"]["slew"]["extra"] = "not allowed"

    with pytest.raises(CommandParseError) as exc_info:
        parse_raw_llm_response(
            _raw_response(_content(payload)),
            command_duration_min_s=0.5,
            command_duration_max_s=3.0,
        )

    assert "left_joystick.slew.extra" in {
        error.field_path for error in exc_info.value.errors
    }


def test_parser_strips_all_model_forged_authoritative_metadata() -> None:
    parsed = parse_raw_llm_response(
        _raw_response(_content(_payload()), response_id="resp-authoritative"),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
    )

    assert parsed.schema_version == "1.0"
    assert parsed.command_id == "cmd-resp-authoritative"
    assert parsed.response_id == "resp-authoritative"
    assert parsed.observation_id == "obs-001"
    assert parsed.source_snapshot_id == "snap-001"
    assert parsed.operator_id == "op-001"
    assert parsed.crane_id == "C1"
    assert parsed.time_s == 12.5


@pytest.mark.parametrize("duration", [0.5, 3.0])
def test_parser_accepts_exact_configured_duration_boundaries(duration: float) -> None:
    parsed = parse_raw_llm_response(
        _raw_response(_content(_payload(command_duration_s=duration))),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
    )

    assert parsed.command_duration_s == duration


def test_validation_errors_from_command_parse_error_returns_original_errors() -> None:
    errors = [
        CommandValidationError(
            error_code="LLM_E_002",
            field_path="task_action",
            message="bad task action",
            raw_fragment='"attach"',
        )
    ]
    exc = CommandParseError("parse failed", errors=errors)

    assert validation_errors_from_exception(exc) is errors


def test_parse_missing_required_field_reports_precise_field_path() -> None:
    payload = _payload()
    payload.pop("deadman_pressed")

    with pytest.raises(CommandParseError) as exc_info:
        parse_raw_llm_response(
            _raw_response(_content(payload)),
            command_duration_min_s=0.5,
            command_duration_max_s=3.0,
        )

    assert "deadman_pressed" in {error.field_path for error in exc_info.value.errors}


def test_parse_runtime_duration_error_uses_parsed_duration_as_raw_fragment() -> None:
    with pytest.raises(CommandParseError) as exc_info:
        parse_raw_llm_response(
            _raw_response(_content(_payload(command_duration_s=2.5))),
            command_duration_min_s=0.5,
            command_duration_max_s=2.0,
        )

    error = exc_info.value.errors[0]
    assert error.field_path == "command_duration_s"
    assert error.raw_fragment == "2.5"
    assert "between 0.5 and 2.0" in error.message
