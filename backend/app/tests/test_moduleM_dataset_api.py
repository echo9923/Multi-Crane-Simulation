from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _client(*, dataset_root: Path | None = None) -> TestClient:
    app = create_app()
    if dataset_root is not None:
        app.state.dataset_root = dataset_root
    return TestClient(app)


def _dataset(root: Path, dataset_id: str, *, summary: dict | None = None) -> Path:
    dataset_dir = root / dataset_id
    metadata_dir = dataset_dir / "metadata"
    metadata_dir.mkdir(parents=True)
    if summary is not None:
        (metadata_dir / "dataset_summary.json").write_text(
            json.dumps(summary),
            encoding="utf-8",
        )
    return dataset_dir


def test_list_datasets_returns_empty_list_for_empty_root(tmp_path: Path) -> None:
    client = _client(dataset_root=tmp_path)

    response = client.get("/datasets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"] == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_datasets_supports_pagination_and_summary_availability(tmp_path: Path) -> None:
    _dataset(tmp_path, "dataset-a", summary={"dataset_id": "dataset-a", "num_episodes": 3})
    _dataset(tmp_path, "dataset-b", summary=None)
    client = _client(dataset_root=tmp_path)

    response = client.get("/datasets?limit=1&offset=0")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["items"]) == 1
    assert data["items"][0]["dataset_id"] == "dataset-a"
    assert data["items"][0]["summary_available"] is True
    assert data["items"][0]["num_episodes"] == 3


def test_get_dataset_summary_reads_summary_file(tmp_path: Path) -> None:
    _dataset(
        tmp_path,
        "dataset-a",
        summary={"dataset_id": "dataset-a", "num_episodes": 3, "risk_ratio": 0.2},
    )
    client = _client(dataset_root=tmp_path)

    response = client.get("/datasets/dataset-a/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["dataset_id"] == "dataset-a"
    assert payload["data"]["summary"]["risk_ratio"] == 0.2


def test_missing_dataset_returns_not_found(tmp_path: Path) -> None:
    client = _client(dataset_root=tmp_path)

    response = client.get("/datasets/missing/summary")

    assert response.status_code == 404
    assert response.json()["code"] == "M_E_DATASET_NOT_FOUND"


def test_dataset_root_not_configured_returns_not_implemented() -> None:
    client = _client()

    response = client.get("/datasets")

    assert response.status_code == 501
    assert response.json()["code"] == "M_E_DATASET_NOT_IMPLEMENTED"


def test_dataset_id_rejects_path_traversal(tmp_path: Path) -> None:
    client = _client(dataset_root=tmp_path)

    response = client.get("/datasets/..%2Fsecret/summary")

    assert response.status_code in {404, 422}
    assert response.json()["code"] == "M_E_DATASET_NOT_FOUND"
