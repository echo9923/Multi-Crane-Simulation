from __future__ import annotations

import json

from backend.app.schemas.command import CommandValidationError, ParsedCommand
from backend.app.schemas.enums import OperatorProfile, RiskPromptMode
from backend.app.schemas.observation import (
    AvailableActions,
    AxisCommand as ObservationAxisCommand,
    JoystickCommandSummary,
    LeftJoystickCommand as ObservationLeftJoystickCommand,
    MemorySummary,
    Observation,
    RightJoystickCommand as ObservationRightJoystickCommand,
    SafetyHint,
    SelfStateSummary,
    TaskObservationSummary,
    WeatherObservationSummary,
)
from backend.app.sim.prompt_builder import (
    PROFILE_BEHAVIOR_PARAMS,
    build_operator_messages,
    build_retry_prompt,
    build_user_prompt,
    get_profile_behavior_params,
    get_profile_prompt,
)


def _observation(
    *,
    profile: OperatorProfile = OperatorProfile.NORMAL,
    risk_prompt_mode: RiskPromptMode = RiskPromptMode.R0,
    safety_hint: SafetyHint | None = None,
) -> Observation:
    return Observation(
        observation_id="obs-001",
        source_snapshot_id="snap-001",
        operator_id="op-001",
        crane_id="C1",
        time_s=12.5,
        operator_profile=profile,
        risk_prompt_mode=risk_prompt_mode,
        task=TaskObservationSummary(
            stage="move_to_pickup",
            has_active_task=True,
            type="easy_task",
            priority="high",
            deadline_s=60.0,
            current_target_relative_direction="right_front",
            current_target_distance_m=18.5,
            current_target_height_delta_m=-2.0,
            signal_hint="slow approach",
        ),
        self_state=SelfStateSummary(
            slew_angle_deg=35.0,
            slew_motion="hold",
            trolley_r_m=20.0,
            hook_h_m=12.0,
            load_attached=False,
            load_weight_t=0.0,
            current_command=JoystickCommandSummary(
                left_joystick=ObservationLeftJoystickCommand(
                    slew=ObservationAxisCommand(direction="neutral", gear=0),
                    trolley=ObservationAxisCommand(direction="neutral", gear=0),
                ),
                right_joystick=ObservationRightJoystickCommand(
                    hoist=ObservationAxisCommand(direction="neutral", gear=0)
                ),
            ),
        ),
        weather=WeatherObservationSummary(
            wind_speed_m_s=3.0,
            gust_m_s=5.0,
            wind_direction_deg=90.0,
            visibility="good",
            visibility_confidence=0.9,
        ),
        safety_hint=safety_hint,
        available_actions=AvailableActions(),
        memory=MemorySummary(event_summary=["previous risk cleared"]),
    )


def _extract_json_block(prompt: str, label: str):
    start_marker = f"<{label}>"
    end_marker = f"</{label}>"
    start = prompt.index(start_marker) + len(start_marker)
    end = prompt.index(end_marker)
    return json.loads(prompt[start:end].strip())


def test_profile_behavior_params_are_returned_as_defensive_copies() -> None:
    behavior = get_profile_behavior_params(OperatorProfile.CONSERVATIVE)
    behavior["risk_sensitivity"] = -1

    assert PROFILE_BEHAVIOR_PARAMS[OperatorProfile.CONSERVATIVE]["risk_sensitivity"] == 0.9
    assert get_profile_behavior_params(OperatorProfile.CONSERVATIVE)["risk_sensitivity"] == 0.9


def test_each_profile_prompt_exposes_expected_driving_style_contract() -> None:
    expected_fragments = {
        OperatorProfile.NORMAL: ["1-3", "4"],
        OperatorProfile.CONSERVATIVE: ["1-2", "neutral"],
        OperatorProfile.AGGRESSIVE: ["3-5", "multi"],
        OperatorProfile.NOVICE: ["1-2", "4-5"],
        OperatorProfile.FATIGUED: ["1-3", "stale_command_bias"],
    }

    for profile, fragments in expected_fragments.items():
        profile_prompt = get_profile_prompt(profile)
        behavior = get_profile_behavior_params(profile)
        combined = profile_prompt + json.dumps(behavior, sort_keys=True)
        for fragment in fragments:
            assert fragment in combined


def test_build_operator_messages_treats_empty_retry_errors_as_no_retry_message() -> None:
    messages = build_operator_messages(
        _observation(),
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
        retry_errors=[],
    )

    assert [message.role for message in messages] == ["system", "user"]


def test_user_prompt_embeds_r1_safety_hint_as_parseable_observation_only() -> None:
    safety_hint = SafetyHint(
        source="online_risk",
        risk_level="high",
        nearest_neighbor="C2",
        nearest_object_type="jib-hook",
        clearance_now_m=2.0,
        estimated_clearance_next_5s_m=1.4,
        relative_motion="closing",
        confidence=0.85,
        suggestion="slow slew and observe",
    )
    observation = _observation(
        risk_prompt_mode=RiskPromptMode.R1,
        safety_hint=safety_hint,
    )
    prompt = build_user_prompt(
        observation,
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
    )

    observation_json = _extract_json_block(prompt, "observation_json")
    schema_json = _extract_json_block(prompt, "command_schema_json")

    assert observation_json["risk_prompt_mode"] == "R1"
    assert observation_json["safety_hint"]["risk_level"] == "high"
    assert observation_json["safety_hint"]["relative_motion"] == "closing"
    assert schema_json["properties"]["task_action"]["enum"] == [
        "none",
        "request_attach",
        "request_release",
    ]
    assert "offline_label" not in json.dumps(observation_json, sort_keys=True)


def test_retry_prompt_json_block_omits_retryable_and_schema_noise() -> None:
    prompt = build_retry_prompt(
        [
            CommandValidationError(
                error_code="LLM_E_002",
                field_path="left_joystick.slew.gear",
                message="Input should be less than or equal to 5",
                raw_fragment="6",
                retryable=True,
            )
        ]
    )

    errors_json = _extract_json_block(prompt, "validation_errors_json")

    assert errors_json == [
        {
            "error_code": "LLM_E_002",
            "field_path": "left_joystick.slew.gear",
            "message": "Input should be less than or equal to 5",
            "raw_fragment": "6",
        }
    ]


def test_operator_messages_keep_system_message_first_for_every_profile() -> None:
    for profile in OperatorProfile:
        messages = build_operator_messages(
            _observation(profile=profile),
            command_schema=ParsedCommand.model_json_schema(),
            command_duration_min_s=0.5,
            command_duration_max_s=3.0,
            command_duration_default_s=1.0,
        )

        assert messages[0].role == "system"
        assert f"operator_profile: {profile.value}" in messages[0].content
        assert messages[1].role == "user"
        assert "<observation_json>" in messages[1].content


def test_prompt_messages_do_not_contain_secret_or_future_truth_markers() -> None:
    messages = build_operator_messages(
        _observation(),
        command_schema=ParsedCommand.model_json_schema(),
        command_duration_min_s=0.5,
        command_duration_max_s=3.0,
        command_duration_default_s=1.0,
    )
    combined = "\n".join(message.content for message in messages).lower()

    for forbidden in [
        "api_key",
        "authorization",
        "token",
        "offline_ttc",
        "offline_label",
        "future_min_distance",
        "planned_start_s",
    ]:
        assert forbidden not in combined
