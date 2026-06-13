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
