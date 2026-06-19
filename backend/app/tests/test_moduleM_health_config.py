import json
from pathlib import Path

import pytest

from backend.app.tests.test_config_schema import FIXTURE_DIR, load_fixture


def _client():
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    return TestClient(create_app())


def test_health_endpoint_uses_uniform_success_response() -> None:
    client = _client()

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["message"] == "ok"
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["api_schema_version"] == "1.0"
    assert payload["data"]["modules"]["api"] == "available"
    assert payload["data"]["modules"]["config"] == "available"


def test_openapi_documents_health_and_scenario_validate_routes() -> None:
    client = _client()

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/scenarios/validate" in paths


def test_validate_scenario_accepts_valid_demo_config() -> None:
    client = _client()

    response = client.post(
        "/scenarios/validate",
        json={"config_path": str(FIXTURE_DIR / "demo_valid.yaml")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["valid"] is True
    assert payload["data"]["resolved_config_hash"]
    assert payload["data"]["errors"] == []


def test_validate_scenario_accepts_inline_config_without_dataset() -> None:
    client = _client()
    scenario = load_fixture("scenario_valid.yaml")
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["provider"] = "mock"
    experiment["llm"]["api_key_env"] = None

    response = client.post(
        "/scenarios/validate",
        json={"scenario": scenario, "experiment": experiment},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["valid"] is True
    assert payload["data"]["resolved_config_hash"]


def test_validate_scenario_rejects_ambiguous_config_sources() -> None:
    client = _client()

    response = client.post(
        "/scenarios/validate",
        json={
            "config_path": str(FIXTURE_DIR / "demo_valid.yaml"),
            "scenario": {"scenario_id": "ambiguous"},
        },
    )

    assert response.status_code in {400, 422}
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert payload["data"] is None
    assert "config_path" in json.dumps(payload["details"])


def test_validate_scenario_missing_path_returns_uniform_error() -> None:
    client = _client()
    missing_path = Path("missing/demo.yaml")

    response = client.post(
        "/scenarios/validate",
        json={"config_path": str(missing_path)},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert payload["data"] is None
    assert payload["message"]
    assert payload["details"]["config_kind"] == "scenario"


def test_validate_scenario_error_response_redacts_inline_secret() -> None:
    client = _client()
    scenario = load_fixture("scenario_valid.yaml")
    experiment = load_fixture("experiment_valid.yaml")
    secret = "sk-inline-secret-123456"
    experiment["llm"]["api_key"] = secret
    experiment["llm"]["api_key_env"] = None
    scenario["layout"]["mode"] = "unknown_mode"

    response = client.post(
        "/scenarios/validate",
        json={"scenario": scenario, "experiment": experiment},
    )

    assert response.status_code == 422
    response_text = response.text
    assert secret not in response_text
    assert response.json()["code"] == "M_E_CONFIG_INVALID"


def test_validate_scenario_pydantic_error_redacts_inline_secret_input() -> None:
    client = _client()
    scenario = load_fixture("scenario_valid.yaml")
    experiment = load_fixture("experiment_valid.yaml")
    secret = "sk-inline-secret-123456"
    experiment["llm"]["api_key"] = secret
    experiment["llm"]["api_key_env"] = None
    experiment["llm"].pop("model")

    response = client.post(
        "/scenarios/validate",
        json={"scenario": scenario, "experiment": experiment},
    )

    assert response.status_code == 422
    assert secret not in response.text
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert payload["details"]["field_path"] == "llm.model"


def test_validate_scenario_returns_manual_layout_error_details() -> None:
    client = _client()
    scenario = load_fixture("scenario_valid.yaml")
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["provider"] = "mock"
    experiment["llm"]["api_key_env"] = None
    scenario["layout"]["mode"] = "manual"
    scenario["layout"]["num_cranes"] = 2
    scenario["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [-60.0, -60.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
        {
            "crane_id": "C2",
            "model_id": "generic_flat_top_55m",
            "base": [-55.0, -60.0, 0.0],
            "mast_height_m": 45.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        },
    ]

    response = client.post(
        "/scenarios/validate",
        json={"scenario": scenario, "experiment": experiment},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert payload["message"] == "crane bases are too close"
    assert payload["details"]["reason"] == "root_distance_too_small"
    assert payload["details"]["crane_id_a"] == "C1"
    assert payload["details"]["crane_id_b"] == "C2"
    assert payload["details"]["min_base_distance_m"] == 8.0


def test_validate_scenario_rejects_unreachable_manual_task_height() -> None:
    client = _client()
    scenario = load_fixture("scenario_valid.yaml")
    experiment = load_fixture("experiment_valid.yaml")
    experiment["llm"]["provider"] = "mock"
    experiment["llm"]["api_key_env"] = None
    scenario["layout"]["mode"] = "manual"
    scenario["layout"]["num_cranes"] = 1
    scenario["cranes"] = [
        {
            "crane_id": "C1",
            "model_id": "generic_flat_top_55m",
            "base": [0.0, 0.0, 0.0],
            "mast_height_m": 40.0,
            "theta_init_deg": 0.0,
            "slew": {"mode": "continuous"},
        }
    ]
    scenario["site"]["forbidden_zones"] = []
    scenario["site"]["material_zones"] = [
        {
            "zone_id": "ground",
            "type": "box",
            "center": [12.0, 0.0, 0.0],
            "size": [6.0, 6.0, 0.4],
            "surface_z_m": 0.0,
            "load_types": ["rebar_bundle"],
        }
    ]
    scenario["site"]["work_zones"] = [
        {
            "zone_id": "too_high_floor",
            "type": "box",
            "center": [18.0, 0.0, 39.0],
            "size": [6.0, 6.0, 0.4],
            "surface_z_m": 39.0,
            "accepted_load_types": ["rebar_bundle"],
        }
    ]
    scenario["tasks"]["generation_mode"] = "manual"
    scenario["tasks"]["manual_tasks"] = [
        {
            "task_id": "T_TOO_HIGH",
            "crane_id": "C1",
            "task_type": "easy_task",
            "pickup_zone_id": "ground",
            "dropoff_zone_id": "too_high_floor",
            "load_type": "rebar_bundle",
            "priority": "medium",
        }
    ]

    response = client.post(
        "/scenarios/validate",
        json={"scenario": scenario, "experiment": experiment},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "M_E_CONFIG_INVALID"
    assert payload["message"] == "task point hook target height is unreachable"
    assert payload["details"]["config_error_code"] == "TASK_E_001"
    assert payload["details"]["reason"] == "point_height_unreachable"
    assert payload["details"]["task_id"] == "T_TOO_HIGH"
