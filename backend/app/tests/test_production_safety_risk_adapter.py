from __future__ import annotations

from types import SimpleNamespace

from backend.app.api.production_runner import ProductionRiskAdapter, ProductionSafetyAdapter
from backend.app.schemas.config import ForbiddenZonePolicyConfig, RiskConfig, ScenarioConfig
from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.sim.physics import initialize_crane_state, recompute_state_geometry
from backend.app.tests.test_config_schema import load_fixture
from backend.app.tests.test_moduleH_acceptance import _command, _configs, _weather


def _risk_config() -> RiskConfig:
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
                "high": 20.0,
                "near_miss": 3.0,
            },
            "ttc_threshold_level": "high",
            "wind_safe_distance_factor": {
                "enabled": False,
                "extra_clearance_per_10m_s_wind_m": 2.0,
            },
        }
    )


def _scenario(risk_config: RiskConfig) -> ScenarioConfig:
    raw = load_fixture("scenario_valid.yaml")
    raw["risk"] = risk_config.model_dump(mode="json")
    raw["site"]["forbidden_zone_policy"] = {
        "mode": ForbiddenZonePolicyMode.HARD.value,
        "record_violation": True,
    }
    return ScenarioConfig.model_validate(raw)


def _states(configs):
    states = []
    for config in configs:
        state = initialize_crane_state(config).model_copy(
            update={"trolley_r_m": 10.0, "hook_h_m": 20.0}
        )
        states.append(recompute_state_geometry(config, state))
    return states


def test_production_safety_adapter_applies_online_risk_intervention() -> None:
    configs = _configs(count=2, spacing_m=30.0)
    states = _states(configs)
    risk_config = _risk_config()
    adapter = ProductionSafetyAdapter(
        scenario=_scenario(risk_config),
        risk_config=risk_config,
        safety_mode=SafetyMode.S2,
        dt_s=0.1,
    )
    snapshot = SimpleNamespace(
        snapshot_id="SNAP-prod-safety",
        time_s=5.0,
        crane_states=states,
        crane_configs=configs,
        weather_state=_weather(),
    )

    commands = adapter.apply_pipeline(
        [_command(config, snapshot_id=snapshot.snapshot_id) for config in configs],
        snapshot=snapshot,
    )

    assert len(commands) == 2
    assert adapter.last_result.online_risk.global_risk_level == "high"
    assert all(command.modified for command in commands)
    assert all(command.interventions for command in commands)
    assert {command.interventions[0].action for command in commands} == {
        "limit_speed_on_high_risk"
    }
    assert all("risk_intervention" in command.modification_reasons for command in commands)


def test_production_risk_adapter_fills_missing_commands_for_all_cranes() -> None:
    configs = _configs(count=2, spacing_m=30.0)
    states = _states(configs)
    risk_config = _risk_config()
    adapter = ProductionRiskAdapter(
        risk_config=risk_config,
        crane_configs=configs,
        weather_state=_weather(),
    )
    snapshot = SimpleNamespace(
        snapshot_id="SNAP-prod-risk",
        time_s=5.0,
        weather_state=_weather(),
        crane_states=states,
        crane_configs=configs,
    )

    result = adapter.evaluate_predecision(snapshot=snapshot, commands={})

    assert len(result.online_risk.pairs) == 1
    assert set(result.hints) == {"C1", "C2"}
