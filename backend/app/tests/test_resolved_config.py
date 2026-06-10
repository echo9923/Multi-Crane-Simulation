from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.core.config_hash import ConfigHashError, compute_resolved_config_hash
from backend.app.core.config_resolver import resolve_config
from backend.app.tests.test_config_schema import load_fixture


def _resolved_from_raw(scenario_raw=None, experiment_raw=None):
    scenario_raw = scenario_raw or load_fixture("scenario_valid.yaml")
    experiment_raw = experiment_raw or load_fixture("experiment_valid.yaml")
    return resolve_config(scenario_raw, experiment_raw)


def test_same_input_generates_same_resolved_config_hash() -> None:
    first = _resolved_from_raw()
    second = _resolved_from_raw()

    assert first.resolved_config_hash == second.resolved_config_hash


def test_hash_excludes_run_path() -> None:
    experiment_a = load_fixture("experiment_valid.yaml")
    experiment_b = deepcopy(experiment_a)
    experiment_b["output"]["run_root"] = "other-runs"

    first = _resolved_from_raw(experiment_raw=experiment_a)
    second = _resolved_from_raw(experiment_raw=experiment_b)

    assert first.resolved_config_hash == second.resolved_config_hash


def test_hash_excludes_created_timestamp_metadata() -> None:
    resolved = _resolved_from_raw()
    payload = resolved.model_dump(mode="json")
    payload["created_at"] = "2026-06-10T00:00:00Z"

    assert compute_resolved_config_hash(payload) == resolved.resolved_config_hash


def test_changing_sim_duration_changes_hash() -> None:
    experiment_a = load_fixture("experiment_valid.yaml")
    experiment_b = deepcopy(experiment_a)
    experiment_b["sim"]["duration_s"] = 900

    assert (
        _resolved_from_raw(experiment_raw=experiment_a).resolved_config_hash
        != _resolved_from_raw(experiment_raw=experiment_b).resolved_config_hash
    )


def test_changing_risk_prompt_mode_changes_hash() -> None:
    experiment_a = load_fixture("experiment_valid.yaml")
    experiment_b = deepcopy(experiment_a)
    experiment_b["risk_prompt_mode"] = "R0"

    assert (
        _resolved_from_raw(experiment_raw=experiment_a).resolved_config_hash
        != _resolved_from_raw(experiment_raw=experiment_b).resolved_config_hash
    )


def test_changing_safety_mode_changes_hash() -> None:
    experiment_a = load_fixture("experiment_valid.yaml")
    experiment_b = deepcopy(experiment_a)
    experiment_b["safety_mode"] = "S2"

    assert (
        _resolved_from_raw(experiment_raw=experiment_a).resolved_config_hash
        != _resolved_from_raw(experiment_raw=experiment_b).resolved_config_hash
    )


def test_changing_provider_model_or_temperature_changes_hash() -> None:
    experiment_a = load_fixture("experiment_valid.yaml")
    experiment_b = deepcopy(experiment_a)
    experiment_c = deepcopy(experiment_a)
    experiment_b["llm"]["model"] = "deepseek-reasoner"
    experiment_c["llm"]["temperature"] = 0.2

    baseline_hash = _resolved_from_raw(experiment_raw=experiment_a).resolved_config_hash

    assert _resolved_from_raw(experiment_raw=experiment_b).resolved_config_hash != baseline_hash
    assert _resolved_from_raw(experiment_raw=experiment_c).resolved_config_hash != baseline_hash


def test_hash_excludes_key_masked_and_full_api_key() -> None:
    experiment_a = load_fixture("experiment_valid.yaml")
    experiment_b = deepcopy(experiment_a)
    experiment_a["llm"]["api_key"] = "sk-inline-key-aaaaaaaa"
    experiment_b["llm"]["api_key"] = "sk-inline-key-bbbbbbbb"

    first = _resolved_from_raw(experiment_raw=experiment_a)
    second = _resolved_from_raw(experiment_raw=experiment_b)
    changed_mask = first.model_copy(
        update={
            "provider": first.provider.model_copy(update={"key_masked": "different"})
        }
    )

    assert first.resolved_config_hash == second.resolved_config_hash
    assert (
        compute_resolved_config_hash(changed_mask.model_dump(mode="json"))
        == first.resolved_config_hash
    )


def test_manual_layout_preserves_crane_input() -> None:
    scenario = load_fixture("scenario_valid.yaml")
    scenario["layout"]["mode"] = "manual"
    scenario["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0, 0, 0],
            "mast_height_m": 45,
            "theta_init_deg": 20,
            "slew": {"mode": "continuous"},
        }
    ]

    resolved = _resolved_from_raw(scenario_raw=scenario)

    assert resolved.layout.mode == "manual"
    assert resolved.layout.manual_cranes[0]["crane_id"] == "C1"
    assert resolved.layout.resolved_cranes is None


def test_auto_layout_does_not_generate_cranes() -> None:
    resolved = _resolved_from_raw()

    assert resolved.layout.mode == "auto"
    assert resolved.layout.manual_cranes is None
    assert resolved.layout.resolved_cranes is None
    assert resolved.layout.auto_params["num_cranes"] == 4


def test_defaults_applied_tracks_derived_seeds() -> None:
    resolved = _resolved_from_raw()

    paths = {item.field_path for item in resolved.defaults_applied}

    assert "seeds.layout" in paths
    assert "seeds.task" in paths
    assert resolved.seeds.scenario == 20260101
    assert resolved.seeds.experiment == 20260101


def test_hash_error_for_unserializable_payload_maps_to_exception() -> None:
    with pytest.raises(ConfigHashError):
        compute_resolved_config_hash({"bad": object()})
