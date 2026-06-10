from __future__ import annotations

from backend.app.core.config_resolver import resolve_config
from backend.app.tests.test_config_schema import load_fixture


def _manual_raw() -> dict:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = 2
    raw["cranes"] = [
        {
            "crane_id": "SITE_A",
            "model_id": "generic_flat_top_55m",
            "base": [-60.0, -60.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 30.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "SITE_B",
            "model_id": "generic_flat_top_55m",
            "base": [45.0, 45.0, 0.0],
            "mast_height_m": 51.0,
            "theta_init_deg": 210.0,
            "slew": {"mode": "continuous"},
        },
    ]
    return raw


def _resolve(raw: dict):
    return resolve_config(raw, load_fixture("experiment_valid.yaml"))


def test_manual_resolved_layout_keeps_input_and_resolved_output_separate() -> None:
    raw = _manual_raw()

    resolved = _resolve(raw)

    assert resolved.layout.mode == "manual"
    assert resolved.layout.auto_params is None
    assert resolved.layout.manual_cranes == raw["cranes"]
    assert resolved.layout.resolved_cranes != raw["cranes"]
    assert all("root" in crane for crane in resolved.layout.resolved_cranes)
    assert all("hook_h_min_world_m" in crane for crane in resolved.layout.resolved_cranes)


def test_yaml_model_override_is_reflected_in_snapshot_and_resolved_cranes() -> None:
    raw = _manual_raw()
    raw["crane_models"][0]["jib_length_m"] = 60.0
    raw["crane_models"][0]["trolley_r_max_m"] = 55.0
    raw["crane_models"][0]["tip_load_t"] = 2.0

    resolved = _resolve(raw)

    snapshot = resolved.layout.model_library_snapshot["generic_flat_top_55m"]
    crane = resolved.layout.resolved_cranes[0]
    assert snapshot["source"] == "yaml_override"
    assert snapshot["jib_length_m"] == 60.0
    assert crane["jib_length_m"] == 60.0
    assert crane["model"]["tip_load_t"] == 2.0


def test_resolved_hash_changes_when_model_parameters_change() -> None:
    baseline = _resolve(_manual_raw()).resolved_config_hash
    changed = _manual_raw()
    changed["crane_models"][0]["tip_load_t"] = 1.25

    assert _resolve(changed).resolved_config_hash != baseline


def test_auto_resolved_layout_has_auto_params_and_auto_sources() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["num_cranes"] = 3

    resolved = _resolve(raw)

    assert resolved.layout.mode == "auto"
    assert resolved.layout.manual_cranes is None
    assert resolved.layout.auto_params == raw["layout"]
    assert len(resolved.layout.resolved_cranes) == 3
    assert {crane["source"] for crane in resolved.layout.resolved_cranes} == {"auto"}
    assert resolved.layout.layout_diagnostics["quality_score"] is not None
    assert len(resolved.layout.layout_diagnostics["pair_diagnostics"]) == 3


def test_resolved_cranes_are_json_safe_static_configs_only() -> None:
    resolved = _resolve(_manual_raw())
    forbidden_runtime_fields = {
        "theta_dot_rad_s",
        "trolley_v_m_s",
        "hook_v_m_s",
        "load_attached",
        "task_id",
        "task_stage",
    }

    for crane in resolved.layout.resolved_cranes:
        assert forbidden_runtime_fields.isdisjoint(crane)
