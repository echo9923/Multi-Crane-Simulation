from __future__ import annotations

from copy import deepcopy
from math import pi

from backend.app.core.config_resolver import resolve_config
from backend.app.tests.test_config_schema import load_fixture


def _manual_raw(*, base=None, mast_height_m: float = 45.0) -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 2
    raw["cranes"] = [
        {
            "crane_id": "TC_A",
            "model_id": "generic_flat_top_55m",
            "base": base or [-60.0, -60.0, 0.0],
            "mast_height_m": mast_height_m,
            "theta_init_deg": 90.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "TC_B",
            "model_id": "generic_flat_top_55m",
            "base": [45.0, 45.0, 0.0],
            "mast_height_m": 50.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
    ]
    return raw


def _resolved(scenario_raw: dict):
    return resolve_config(scenario_raw, load_fixture("experiment_valid.yaml"))


def test_valid_manual_scenario_generates_resolved_cranes() -> None:
    resolved = _resolved(_manual_raw())

    assert len(resolved.layout.resolved_cranes) == 2
    assert resolved.layout.resolved_cranes[0]["crane_id"] == "TC_A"
    assert resolved.layout.resolved_cranes[0]["source"] == "manual"


def test_crane_config_geometry_and_hook_height_bounds() -> None:
    crane = _resolved(_manual_raw()).layout.resolved_cranes[0]

    assert crane["root"] == [-60.0, -60.0, 45.0]
    assert crane["theta_init_rad"] == pi / 2
    assert crane["theta_sin"] == 1.0
    assert abs(crane["theta_cos"]) < 1e-12
    assert crane["hook_h_min_world_m"] == 0.0
    assert crane["hook_h_max_world_m"] == 43.0
    assert crane["hook_h_max_world_m"] <= crane["root"][2]
    assert crane["jib_length_m"] == 55.0
    assert crane["model"]["rated_moment_t_m"] == 90.0


def test_layout_diagnostics_and_model_snapshot_are_resolved() -> None:
    layout = _resolved(_manual_raw()).layout

    assert layout.layout_diagnostics["mode"] == "manual"
    assert layout.layout_diagnostics["num_cranes"] == 2
    assert len(layout.layout_diagnostics["pair_diagnostics"]) == 1
    assert layout.layout_diagnostics["quality_score"] is None
    assert "generic_flat_top_55m" in layout.model_library_snapshot


def test_resolved_hash_changes_with_crane_static_parameters() -> None:
    baseline = _resolved(_manual_raw()).resolved_config_hash
    moved = _resolved(_manual_raw(base=[-70.0, -60.0, 0.0])).resolved_config_hash
    taller = _resolved(_manual_raw(mast_height_m=46.0)).resolved_config_hash

    assert moved != baseline
    assert taller != baseline


def test_resolved_output_does_not_contain_full_llm_key() -> None:
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["api_key"] = "sk-inline-key-aaaaaaaa"

    resolved = resolve_config(_manual_raw(), experiment)

    assert "sk-inline-key-aaaaaaaa" not in str(resolved.model_dump(mode="json"))


def test_pair_diagnostics_scale_to_n_cranes() -> None:
    raw = _manual_raw()
    raw["layout"]["num_cranes"] = 3
    raw["cranes"].append(
        {
            "crane_id": "TC_C",
            "model_id": "generic_flat_top_55m",
            "base": [70.0, -40.0, 0.0],
            "mast_height_m": 55.0,
            "theta_init_deg": 180.0,
            "slew": {"mode": "continuous"},
        }
    )

    diagnostics = _resolved(raw).layout.layout_diagnostics

    assert len(diagnostics["pair_diagnostics"]) == 3
