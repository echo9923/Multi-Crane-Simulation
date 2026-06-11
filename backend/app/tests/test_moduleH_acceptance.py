from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import (
    ForbiddenZonePolicyConfig,
    RiskConfig,
    ScenarioConfig,
)
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.enums import ForbiddenZonePolicyMode, RiskPromptMode, SafetyMode
from backend.app.schemas.weather import WeatherState, WeatherVisibilityContext
from backend.app.sim.collision import detect_collisions
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.observation import build_safety_hint
from backend.app.sim.physics import initialize_crane_state, recompute_state_geometry
from backend.app.sim.safety import apply_safety_pipeline
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _configs(
    count: int = 2,
    *,
    spacing_m: float = 30.0,
    mast_heights: list[float] | None = None,
):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"C{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [index * spacing_m, 0.0, 0.0],
            "mast_height_m": mast_heights[index] if mast_heights else 45.0 + index * 15.0,
            "theta_init_deg": 0.0 if index == 0 else 180.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _states(configs, *, trolley_r_m: float = 10.0, hook_h_m: float = 20.0):
    states = []
    for config in configs:
        state = initialize_crane_state(config).model_copy(
            update={"trolley_r_m": trolley_r_m, "hook_h_m": hook_h_m}
        )
        states.append(recompute_state_geometry(config, state))
    return states


def _command(
    config,
    *,
    trolley: tuple[str, int] = ("out", 5),
    snapshot_id: str = "snap-H-acceptance",
) -> ParsedCommand:
    return ParsedCommand(
        command_id=f"cmd-{config.crane_id}",
        response_id=f"resp-{config.crane_id}",
        observation_id=f"obs-{config.crane_id}",
        source_snapshot_id=snapshot_id,
        operator_id=f"op-{config.crane_id}",
        crane_id=config.crane_id,
        time_s=5.0,
        left_joystick={
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": trolley[0], "gear": trolley[1]},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=1.0,
        task_action="none",
        attention_target="acceptance",
        confidence=0.8,
        reason="module H acceptance fixture",
    )


def _risk_config(*, high: float = 20.0, near_miss: float = 3.0) -> RiskConfig:
    return RiskConfig.model_validate(
        {
            "geometry_envelope": {
                "jib_radius_m": 0.5,
                "hook_radius_m": 0.5,
                "load_radius_m": 0.8,
            },
            "thresholds_m": {
                "low": 40.0,
                "medium": 30.0,
                "high": high,
                "near_miss": near_miss,
            },
            "ttc_threshold_level": "high",
            "wind_safe_distance_factor": {
                "enabled": False,
                "extra_clearance_per_10m_s_wind_m": 2.0,
            },
        }
    )


def _weather() -> WeatherState:
    return WeatherState(
        time_s=5.0,
        mode="constant",
        wind_speed_m_s=0.0,
        wind_gust_m_s=0.0,
        wind_direction_deg=90.0,
        visibility_level="good",
        rain_level="none",
        fog_level="none",
        generation_seed=1,
        generation_step=0,
    )


def _visibility() -> WeatherVisibilityContext:
    return WeatherVisibilityContext(
        time_s=5.0,
        visibility_level="good",
        neighbor_visibility_radius_m=120.0,
        distance_noise_m=0.0,
        hide_hook_prob=0.0,
        visibility_confidence=0.9,
        distance_precision_m=1.0,
        noise_seed=1,
        profile_source="default",
    )


def _policy() -> ForbiddenZonePolicyConfig:
    return ForbiddenZonePolicyConfig(mode=ForbiddenZonePolicyMode.TASK_ONLY)


def _pipeline(
    *,
    safety_mode: SafetyMode,
    count: int = 2,
    spacing_m: float = 30.0,
    high: float = 20.0,
    mast_heights: list[float] | None = None,
):
    configs = _configs(count=count, spacing_m=spacing_m, mast_heights=mast_heights)
    states = _states(configs)
    commands = [_command(config) for config in configs]
    result = apply_safety_pipeline(
        commands=commands,
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(high=high),
        weather_state=_weather(),
        safety_mode=safety_mode,
        forbidden_zones=[],
        forbidden_zone_policy=_policy(),
        source_snapshot_id="snap-H-acceptance",
        time_s=5.0,
        dt_s=0.1,
    )
    return result, commands, states, configs


def test_online_risk_exports_every_pair_and_feeds_r0_r1_observation_contract() -> None:
    result, _, _, _ = _pipeline(
        safety_mode=SafetyMode.S0,
        count=3,
        spacing_m=80.0,
        high=8.0,
    )

    assert result.episode_status == "running"
    assert len(result.online_risk.pairs) == 3
    assert {pair.pair_id for pair in result.online_risk.pairs} == {
        "C1-C2",
        "C1-C3",
        "C2-C3",
    }
    assert set(result.online_risk.hint_by_crane) == {"C1", "C2", "C3"}

    hint = result.online_risk.hint_by_crane["C1"]
    assert build_safety_hint(
        risk_prompt_mode=RiskPromptMode.R0,
        online_risk=hint,
        visibility=_visibility(),
        distance_precision_m=1.0,
    ) is None
    assert build_safety_hint(
        risk_prompt_mode=RiskPromptMode.R1,
        online_risk=hint,
        visibility=_visibility(),
        distance_precision_m=1.0,
    ) is not None


def test_s0_s1_s2_s3_risk_modes_preserve_contract_boundaries() -> None:
    s0, _, _, _ = _pipeline(safety_mode=SafetyMode.S0)
    s1, _, _, _ = _pipeline(safety_mode=SafetyMode.S1)
    s2, _, _, _ = _pipeline(safety_mode=SafetyMode.S2)
    s3, _, _, _ = _pipeline(safety_mode=SafetyMode.S3)

    assert s0.online_risk.global_risk_level == "high"
    assert all(not command.interventions for command in s0.executed_commands)
    assert all(command.left_joystick.trolley.speed_scale == 1.0 for command in s0.executed_commands)

    assert all(command.interventions for command in s1.executed_commands)
    assert all(not command.modified for command in s1.executed_commands)
    assert {command.interventions[0].action for command in s1.executed_commands} == {
        "ignored_risk_hint"
    }

    assert all(command.modified for command in s2.executed_commands)
    assert all(command.left_joystick.trolley.speed_scale == 0.5 for command in s2.executed_commands)
    assert {command.interventions[0].action for command in s2.executed_commands} == {
        "limit_speed_on_high_risk"
    }

    assert all(command.modified for command in s3.executed_commands)
    assert all(command.left_joystick.trolley.direction == "neutral" for command in s3.executed_commands)
    assert {command.interventions[0].action for command in s3.executed_commands} == {
        "force_stop_on_high_risk"
    }


def test_raw_parsed_command_and_executed_command_are_both_available_to_i_contract() -> None:
    result, raw_commands, _, _ = _pipeline(safety_mode=SafetyMode.S2)

    by_raw_id = {command.command_id: command for command in raw_commands}
    for executed in result.executed_commands:
        raw = by_raw_id[executed.raw_command_id]
        assert executed.raw_command == raw
        assert executed.raw_command.left_joystick.trolley.gear == 5
        assert executed.left_joystick.trolley.speed_scale == 0.5
        assert executed.left_joystick.trolley.source == "risk_intervention"

        required_i_fields = {
            "crane_id",
            "target_slew_velocity_rad_s",
            "target_trolley_velocity_m_s",
            "target_hoist_velocity_m_s",
            "source_command_id",
        }
        assert required_i_fields.issubset(ControlTarget.model_fields)
        assert executed.crane_id
        assert executed.command_id
        assert executed.deadman_pressed is True
        assert executed.emergency_stop is False


def test_collision_result_marks_failed_episode_and_records_trace_event() -> None:
    result, _, _, _ = _pipeline(
        safety_mode=SafetyMode.S0,
        spacing_m=20.0,
        mast_heights=[45.0, 45.0],
    )

    assert result.collision is not None
    assert result.collision.episode_status == "failed_collision"
    assert result.episode_status == "failed_collision"
    assert any(event.event_type == "collision" for event in result.events)


def test_online_risk_payload_has_no_future_or_offline_truth_fields() -> None:
    result, _, _, _ = _pipeline(safety_mode=SafetyMode.S0, count=3, spacing_m=80.0)
    payload_text = str(result.online_risk.model_dump(mode="json"))
    forbidden_fields = {
        "future_min_distance",
        "offline_ttc",
        "offline_label",
        "future_ttc",
        "planned_future_position",
        "neighbor_future_task",
    }

    assert all(pair.used_future_truth is False for pair in result.online_risk.pairs)
    for field_name in forbidden_fields:
        assert field_name not in payload_text


def test_module_h_boundaries_remain_static() -> None:
    files = [
        REPO_ROOT / "backend/app/sim/safety.py",
        REPO_ROOT / "backend/app/sim/risk.py",
        REPO_ROOT / "backend/app/sim/collision.py",
    ]
    forbidden_imports = {
        "backend.app.sim.operator_decision",
        "backend.app.sim.llm_provider",
        "backend.app.sim.recorder",
        "backend.app.sim.offline_label",
    }
    forbidden_names = {"operator_decision", "llm_provider", "offline_label", "recorder"}

    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        assert forbidden_imports.isdisjoint(imports)
        assert forbidden_names.isdisjoint(source.split())


def test_collision_detection_rejects_mismatched_state_and_config_sets() -> None:
    configs = _configs(count=2)
    states = _states(configs)

    with pytest.raises(ValueError, match="match"):
        detect_collisions(
            crane_states=states,
            crane_configs=configs[:1],
            risk_config=_risk_config(),
            source_snapshot_id="snap-H-acceptance",
            time_s=5.0,
        )
