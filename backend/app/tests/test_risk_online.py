from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.app.schemas.command import ParsedCommand
from backend.app.schemas.config import RiskConfig, ScenarioConfig
from backend.app.schemas.weather import WeatherState
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import initialize_crane_state, recompute_state_geometry
from backend.app.sim.risk import (
    classify_risk_level,
    distance_between_cranes,
    evaluate_online_risk,
    evaluate_pair_risk,
    extrapolate_state_short_horizon,
)
from backend.app.sim.safety import apply_mechanical_safety
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _configs(
    count: int = 2,
    *,
    spacing_m: float = 40.0,
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
            "mast_height_m": mast_heights[index] if mast_heights else 45.0,
            "theta_init_deg": 0.0 if index == 0 else 180.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, library, scenario, source="manual")


def _state(config, *, trolley_r_m: float, hook_h_m: float = 20.0, **updates):
    state = initialize_crane_state(config).model_copy(
        update={"trolley_r_m": trolley_r_m, "hook_h_m": hook_h_m, **updates}
    )
    state = recompute_state_geometry(config, state)
    if "load_position" in updates:
        state = state.model_copy(update={"load_position": updates["load_position"]})
    return state


def _risk_config(**overrides) -> RiskConfig:
    payload = {
        "geometry_envelope": {
            "jib_radius_m": 0.5,
            "hook_radius_m": 0.5,
            "load_radius_m": 0.8,
        },
        "thresholds_m": {
            "low": 20.0,
            "medium": 12.0,
            "high": 8.0,
            "near_miss": 3.0,
        },
        "ttc_threshold_level": "high",
        "wind_safe_distance_factor": {
            "enabled": True,
            "extra_clearance_per_10m_s_wind_m": 2.0,
        },
    }
    payload.update(overrides)
    return RiskConfig.model_validate(payload)


def _weather(*, wind: float = 10.0) -> WeatherState:
    return WeatherState(
        time_s=5.0,
        mode="constant",
        wind_speed_m_s=wind,
        wind_gust_m_s=wind,
        wind_direction_deg=90.0,
        visibility_level="good",
        rain_level="none",
        fog_level="none",
        generation_seed=1,
        generation_step=0,
    )


def _command(config, state, *, trolley: tuple[str, int]):
    raw = ParsedCommand(
        command_id=f"cmd-{config.crane_id}",
        response_id="resp",
        observation_id="obs",
        source_snapshot_id="snap-001",
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
        attention_target="risk",
        confidence=0.8,
        reason="fixture",
    )
    executed, _ = apply_mechanical_safety(
        command=raw, state=state, config=config, dt_s=0.1
    )
    return executed


def test_evaluate_online_risk_returns_all_pairs_for_three_cranes() -> None:
    configs = _configs(count=3, spacing_m=80.0)
    states = [_state(config, trolley_r_m=10.0) for config in configs]
    commands = {
        config.crane_id: _command(config, state, trolley=("neutral", 0))
        for config, state in zip(configs, states)
    }

    risk = evaluate_online_risk(
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(),
        weather_state=_weather(),
        proposed_commands=commands,
    )

    assert len(risk.pairs) == 3
    assert {pair.pair_id for pair in risk.pairs} == {"C1-C2", "C1-C3", "C2-C3"}


def test_far_apart_cranes_are_safe() -> None:
    configs = _configs(count=2, spacing_m=180.0)
    states = [_state(config, trolley_r_m=10.0) for config in configs]
    commands = {
        config.crane_id: _command(config, state, trolley=("neutral", 0))
        for config, state in zip(configs, states)
    }

    risk = evaluate_online_risk(
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(),
        weather_state=_weather(wind=0.0),
        proposed_commands=commands,
    )

    assert risk.global_risk_level == "safe"
    assert risk.pairs[0].risk_level == "safe"
    assert risk.pairs[0].used_future_truth is False


def test_current_distance_maps_to_near_miss_and_collision_levels() -> None:
    assert classify_risk_level(
        d_min_online_m=2.5,
        d_hat_min_m=2.5,
        ttc_hat_s=None,
        thresholds_m=_risk_config().thresholds_m,
        d_safe_effective_m=8.0,
    ) == "near_miss"
    assert classify_risk_level(
        d_min_online_m=0.0,
        d_hat_min_m=0.0,
        ttc_hat_s=0.0,
        thresholds_m=_risk_config().thresholds_m,
        d_safe_effective_m=8.0,
    ) == "collision"


def test_short_horizon_detects_closing_pair_and_ttc() -> None:
    configs = _configs(count=2, spacing_m=30.0, mast_heights=[45.0, 60.0])
    state_a = _state(configs[0], trolley_r_m=10.0)
    state_b = _state(configs[1], trolley_r_m=10.0)
    command_a = _command(configs[0], state_a, trolley=("out", 5))
    command_b = _command(configs[1], state_b, trolley=("out", 5))

    pair = evaluate_pair_risk(
        state_a=state_a,
        config_a=configs[0],
        command_a=command_a,
        state_b=state_b,
        config_b=configs[1],
        command_b=command_b,
        risk_config=_risk_config(),
        weather_state=_weather(wind=0.0),
        horizon_s=10.0,
        sample_dt_s=1.0,
    )

    assert pair.relative_motion == "closing"
    assert pair.d_hat_min_m < pair.d_min_online_m
    assert pair.ttc_hat_s is not None


def test_opening_pair_is_detected() -> None:
    configs = _configs(count=2, spacing_m=45.0, mast_heights=[45.0, 60.0])
    state_a = _state(configs[0], trolley_r_m=20.0)
    state_b = _state(configs[1], trolley_r_m=20.0)
    command_a = _command(configs[0], state_a, trolley=("in", 5))
    command_b = _command(configs[1], state_b, trolley=("in", 5))

    pair = evaluate_pair_risk(
        state_a=state_a,
        config_a=configs[0],
        command_a=command_a,
        state_b=state_b,
        config_b=configs[1],
        command_b=command_b,
        risk_config=_risk_config(),
        weather_state=_weather(wind=0.0),
        horizon_s=3.0,
        sample_dt_s=1.0,
    )

    assert pair.relative_motion == "opening"


def test_wind_extra_increases_effective_safe_distance() -> None:
    configs = _configs(count=2, spacing_m=120.0)
    state_a = _state(configs[0], trolley_r_m=10.0)
    state_b = _state(configs[1], trolley_r_m=10.0)
    command_a = _command(configs[0], state_a, trolley=("neutral", 0))
    command_b = _command(configs[1], state_b, trolley=("neutral", 0))

    pair = evaluate_pair_risk(
        state_a=state_a,
        config_a=configs[0],
        command_a=command_a,
        state_b=state_b,
        config_b=configs[1],
        command_b=command_b,
        risk_config=_risk_config(),
        weather_state=_weather(wind=20.0),
        horizon_s=1.0,
        sample_dt_s=1.0,
    )

    assert pair.wind_extra_m == pytest.approx(4.0)
    assert pair.d_safe_effective_m == pytest.approx(pair.base_threshold_m + 4.0)


def test_wind_extra_can_be_disabled() -> None:
    config = _risk_config(
        wind_safe_distance_factor={
            "enabled": False,
            "extra_clearance_per_10m_s_wind_m": 2.0,
        }
    )
    configs = _configs(count=2, spacing_m=120.0)
    state_a = _state(configs[0], trolley_r_m=10.0)
    state_b = _state(configs[1], trolley_r_m=10.0)

    pair = evaluate_pair_risk(
        state_a=state_a,
        config_a=configs[0],
        command_a=_command(configs[0], state_a, trolley=("neutral", 0)),
        state_b=state_b,
        config_b=configs[1],
        command_b=_command(configs[1], state_b, trolley=("neutral", 0)),
        risk_config=config,
        weather_state=_weather(wind=20.0),
        horizon_s=1.0,
        sample_dt_s=1.0,
    )

    assert pair.wind_extra_m == 0.0


def test_distance_between_cranes_uses_load_when_present() -> None:
    configs = _configs(count=2, spacing_m=35.0)
    state_a = _state(
        configs[0],
        trolley_r_m=10.0,
        load_attached=True,
        load_position=[20.0, 0.0, 20.0],
    )
    state_b = _state(configs[1], trolley_r_m=10.0)

    distance, object_a, object_b = distance_between_cranes(
        state_a=state_a,
        config_a=configs[0],
        state_b=state_b,
        config_b=configs[1],
        envelope=_risk_config().geometry_envelope,
    )

    assert object_a in {"load", "hook", "jib"}
    assert object_b in {"load", "hook", "jib"}
    assert distance >= 0.0


def test_online_risk_builds_hint_by_crane() -> None:
    configs = _configs(count=2, spacing_m=45.0)
    states = [_state(config, trolley_r_m=20.0) for config in configs]
    commands = {
        config.crane_id: _command(config, state, trolley=("neutral", 0))
        for config, state in zip(configs, states)
    }

    risk = evaluate_online_risk(
        crane_states=states,
        crane_configs=configs,
        risk_config=_risk_config(),
        weather_state=_weather(),
        proposed_commands=commands,
    )

    assert set(risk.hint_by_crane) == {"C1", "C2"}
    assert risk.hint_by_crane["C1"].source == "online_risk"
    assert risk.hint_by_crane["C1"].nearest_neighbor == "C2"


def test_extrapolate_state_short_horizon_uses_current_command_only() -> None:
    config = _configs(count=1)[0]
    state = _state(config, trolley_r_m=10.0)
    command = _command(config, state, trolley=("out", 5))

    next_state = extrapolate_state_short_horizon(
        state=state,
        config=config,
        command=command,
        dt_s=1.0,
    )

    assert next_state.trolley_r_m > state.trolley_r_m
    assert next_state.crane_id == state.crane_id


@pytest.mark.parametrize(
    ("horizon_s", "sample_dt_s"),
    [(0.0, 1.0), (1.0, 0.0)],
)
def test_invalid_horizon_or_sample_dt_raises_value_error(
    horizon_s: float, sample_dt_s: float
) -> None:
    configs = _configs(count=2)
    states = [_state(config, trolley_r_m=10.0) for config in configs]
    commands = {
        config.crane_id: _command(config, state, trolley=("neutral", 0))
        for config, state in zip(configs, states)
    }

    with pytest.raises(ValueError):
        evaluate_online_risk(
            crane_states=states,
            crane_configs=configs,
            risk_config=_risk_config(),
            weather_state=_weather(),
            proposed_commands=commands,
            horizon_s=horizon_s,
            sample_dt_s=sample_dt_s,
        )


def test_risk_module_does_not_reference_future_or_offline_truth() -> None:
    source = (REPO_ROOT / "backend/app/sim/risk.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_names = {
        "future_min_distance",
        "offline_ttc",
        "offline_label",
        "future_ttc",
        "planned_future_position",
    }
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }

    assert not (names & forbidden_names)
    for forbidden_text in forbidden_names:
        assert forbidden_text not in source
