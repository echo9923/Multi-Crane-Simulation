from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from .errors import ApiException
from .schemas import (
    ApiResponse,
    DatasetListItem,
    DatasetListResponse,
    DatasetSummaryResponse,
    M_E_DATASET_NOT_FOUND,
    M_E_DATASET_NOT_IMPLEMENTED,
)

router = APIRouter()


@router.get("/datasets", response_model=ApiResponse)
def list_datasets(request: Request, limit: int = 50, offset: int = 0) -> ApiResponse:
    if limit < 1 or limit > 500 or offset < 0:
        raise ApiException(
            status_code=422,
            code=M_E_DATASET_NOT_FOUND,
            message="invalid dataset pagination",
            details={"limit": limit, "offset": offset},
        )
    root = _dataset_root(request)
    dataset_dirs = sorted(path for path in root.iterdir() if path.is_dir())
    items = [_dataset_item(path) for path in dataset_dirs]
    page = items[offset : offset + limit]
    response = DatasetListResponse(
        items=page,
        total=len(items),
        limit=limit,
        offset=offset,
    )
    return ApiResponse(data=response.model_dump(mode="json"))


@router.get("/datasets/{dataset_id:path}/summary", response_model=ApiResponse)
def get_dataset_summary(request: Request, dataset_id: str) -> ApiResponse:
    dataset_dir = _dataset_dir(request, dataset_id)
    summary_path = dataset_dir / "metadata" / "dataset_summary.json"
    if not summary_path.is_file():
        raise _dataset_not_found(dataset_id)
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApiException(
            status_code=500,
            code=M_E_DATASET_NOT_FOUND,
            message="failed to read dataset summary",
            details={
                "dataset_id": dataset_id,
                "exception_type": type(exc).__name__,
            },
        ) from exc
    response = DatasetSummaryResponse(dataset_id=dataset_id, summary=summary)
    return ApiResponse(data=response.model_dump(mode="json"))


def _dataset_root(request: Request) -> Path:
    root = getattr(request.app.state, "dataset_root", None)
    if root is None:
        raise ApiException(
            status_code=501,
            code=M_E_DATASET_NOT_IMPLEMENTED,
            message="dataset catalog is not configured",
            details={},
        )
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _dataset_dir(request: Request, dataset_id: str) -> Path:
    if "/" in dataset_id or "\\" in dataset_id or dataset_id in {"", ".", ".."}:
        raise _dataset_not_found(dataset_id)
    root = _dataset_root(request)
    path = (root / dataset_id).resolve()
    if root not in path.parents and path != root:
        raise _dataset_not_found(dataset_id)
    if not path.is_dir():
        raise _dataset_not_found(dataset_id)
    return path


def _dataset_item(path: Path) -> DatasetListItem:
    summary = _read_summary_if_available(path)
    return DatasetListItem(
        dataset_id=path.name,
        path=str(path),
        created_at=summary.get("created_at") if summary else None,
        num_episodes=summary.get("num_episodes") if summary else None,
        summary_available=summary is not None,
    )


def _read_summary_if_available(path: Path) -> dict[str, Any] | None:
    summary_path = path / "metadata" / "dataset_summary.json"
    if not summary_path.is_file():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _dataset_not_found(dataset_id: str) -> ApiException:
    return ApiException(
        status_code=404,
        code=M_E_DATASET_NOT_FOUND,
        message="dataset not found",
        details={"dataset_id": dataset_id},
    )


__all__ = ["router"]
