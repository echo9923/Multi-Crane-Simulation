from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.project_root = tmp_path
    app.state.backend_port = 8765
    return TestClient(app)


def _non_raising_client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.project_root = tmp_path
    app.state.backend_port = 8765
    return TestClient(app, raise_server_exceptions=False)


def test_templates_route_lists_config_templates(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "demo.yaml").write_text(
        "scenario:\n  scenario_id: demo\nexperiment:\n  experiment_id: exp\n",
        encoding="utf-8",
    )

    res = _client(tmp_path).get("/desktop/templates")

    assert res.status_code == 200
    body = res.json()["data"]
    assert body["items"][0]["template_id"] == "demo"
    assert body["items"][0]["scenario_id"] == "demo"


def test_render_route_returns_yaml_text(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "demo.yaml").write_text(
        "scenario:\n  layout:\n    num_cranes: 4\nexperiment:\n  sim:\n    duration_s: 10\n",
        encoding="utf-8",
    )

    res = _client(tmp_path).post(
        "/desktop/config/render",
        json={
            "template_id": "demo",
            "core_overrides": {"scenario.layout.num_cranes": 5},
        },
    )

    assert res.status_code == 200
    assert "num_cranes: 5" in res.json()["data"]["yaml_text"]


def test_patch_route_returns_yaml_text_and_preserves_unrelated_fields(tmp_path: Path) -> None:
    res = _client(tmp_path).post(
        "/desktop/config/patch",
        json={
            "yaml_text": (
                "scenario:\n"
                "  layout:\n"
                "    num_cranes: 4\n"
                "  name: keep-me\n"
                "experiment:\n"
                "  sim:\n"
                "    duration_s: 10\n"
            ),
            "patches": {"scenario.layout.num_cranes": 6},
        },
    )

    assert res.status_code == 200
    yaml_text = res.json()["data"]["yaml_text"]
    assert "num_cranes: 6" in yaml_text
    assert "name: keep-me" in yaml_text
    assert "duration_s: 10" in yaml_text


def test_patch_route_malformed_yaml_returns_config_invalid(tmp_path: Path) -> None:
    res = _non_raising_client(tmp_path).post(
        "/desktop/config/patch",
        json={"yaml_text": "a: [\n", "patches": {"a": 1}},
    )

    assert res.status_code == 400
    assert res.json()["code"] == "M_E_CONFIG_INVALID"


def test_draft_route_scrubs_secret_and_lists_recent(tmp_path: Path) -> None:
    client = _client(tmp_path)

    saved = client.post(
        "/desktop/experiments/draft",
        json={
            "experiment_id": "exp1",
            "yaml_text": "experiment:\n  llm:\n    api_key: sk-real\n",
            "metadata": {"template_id": "demo"},
        },
    )
    assert saved.status_code == 200
    yaml_path = Path(saved.json()["data"]["yaml_path"])
    assert "sk-real" not in yaml_path.read_text(encoding="utf-8")

    recent = client.get("/desktop/experiments/recent")
    assert recent.status_code == 200
    assert recent.json()["data"]["items"][0]["experiment_id"] == "exp1"


def test_draft_route_malformed_yaml_returns_config_invalid(tmp_path: Path) -> None:
    res = _non_raising_client(tmp_path).post(
        "/desktop/experiments/draft",
        json={
            "experiment_id": "exp1",
            "yaml_text": "a: [\n",
            "metadata": {"template_id": "demo"},
        },
    )

    assert res.status_code == 400
    assert res.json()["code"] == "M_E_CONFIG_INVALID"


def test_recent_route_ignores_tampered_metadata_paths(tmp_path: Path) -> None:
    draft = tmp_path / ".desktop" / "experiments" / "exp1"
    draft.mkdir(parents=True)
    (draft / "draft.yaml").write_text("experiment: {}\n", encoding="utf-8")
    (draft / "draft.meta.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp1",
                "yaml_path": str(tmp_path.parent / "outside.yaml"),
                "metadata_path": str(tmp_path.parent / "outside.json"),
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    recent = _client(tmp_path).get("/desktop/experiments/recent")

    assert recent.status_code == 200
    item = recent.json()["data"]["items"][0]
    assert item["experiment_id"] == "exp1"
    assert item["yaml_path"] == str(draft / "draft.yaml")
    assert item["metadata_path"] == str(draft / "draft.meta.json")


def test_runs_and_files_routes(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "episode-1"
    (run / "metadata").mkdir(parents=True)
    (run / "metadata" / "episode_summary.json").write_text(
        json.dumps({"episode_id": "episode-1", "status": "completed"}),
        encoding="utf-8",
    )
    (run / "visual").mkdir()
    (run / "visual" / "frames.jsonl").write_text("{}", encoding="utf-8")
    client = _client(tmp_path)

    runs = client.get("/desktop/runs")
    files = client.get("/desktop/runs/episode-1/files")

    assert runs.status_code == 200
    assert runs.json()["data"]["items"][0]["episode_id"] == "episode-1"
    assert files.status_code == 200
    assert files.json()["data"]["files"][0]["relative_path"] == "metadata/episode_summary.json"


def test_run_files_route_rejects_arbitrary_outside_directories(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-run"
    (outside / "metadata").mkdir(parents=True)
    (outside / "metadata" / "episode_summary.json").write_text(
        json.dumps({"episode_id": "outside-run", "status": "completed"}),
        encoding="utf-8",
    )

    res = _client(tmp_path).get("/desktop/runs/outside-run/files")

    assert res.status_code == 404
    body = res.json()
    assert body["code"] == "M_E_EPISODE_NOT_FOUND"
    assert body["details"]["episode_id"] == "outside-run"


def test_environment_route_reports_project_root(tmp_path: Path) -> None:
    res = _client(tmp_path).get("/desktop/environment")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["project_root"] == str(tmp_path.resolve())
    assert data["backend_port"] == 8765
