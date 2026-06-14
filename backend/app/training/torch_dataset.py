from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from backend.app.schemas.training import StgnnTensorSample

try:  # pragma: no cover - exercised conditionally by environment
    import torch
except ModuleNotFoundError:  # pragma: no cover - current test env may not have torch
    torch = None  # type: ignore[assignment]

TORCH_AVAILABLE = torch is not None


class _DatasetBase:
    pass


if TORCH_AVAILABLE:  # pragma: no branch
    _DatasetBase = torch.utils.data.Dataset  # type: ignore[union-attr, assignment]


class StgnnTorchDataset(_DatasetBase):
    def __init__(
        self,
        samples_or_root: Sequence[StgnnTensorSample] | Path,
        *,
        split: str | None = None,
        load_tensors: bool = True,
    ) -> None:
        _require_torch()
        if isinstance(samples_or_root, Path):
            raise FileNotFoundError(
                "loading tensor samples from converter output is not implemented yet"
            )
        self.samples = [
            sample
            for sample in samples_or_root
            if split is None or sample.metadata.split == split
        ]
        self.load_tensors = load_tensors

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, Any]:
        sample = self.samples[index]
        return {
            "X_node": torch.as_tensor(sample.X_node, dtype=torch.float32),
            "X_edge": torch.as_tensor(sample.X_edge, dtype=torch.float32),
            "A_phy": torch.as_tensor(sample.A_phy, dtype=torch.float32),
            "Y_traj": torch.as_tensor(sample.Y_traj, dtype=torch.float32),
            "Y_risk": torch.as_tensor(sample.Y_risk, dtype=torch.float32),
            "node_mask": torch.as_tensor(sample.node_mask, dtype=torch.bool),
            "edge_mask": torch.as_tensor(sample.edge_mask, dtype=torch.bool),
            "risk_mask": torch.as_tensor(sample.risk_mask, dtype=torch.bool),
            "metadata": sample.metadata.model_dump(mode="json"),
        }


def stgnn_collate_fn(batch: Sequence[dict[str, Any]]) -> dict[str, Any]:
    _require_torch()
    if not batch:
        raise ValueError("batch must not be empty")
    tensor_keys = (
        "X_node",
        "X_edge",
        "A_phy",
        "Y_traj",
        "Y_risk",
        "node_mask",
        "edge_mask",
        "risk_mask",
    )
    collated: dict[str, Any] = {}
    for key in tensor_keys:
        shapes = {tuple(item[key].shape) for item in batch}
        if len(shapes) != 1:
            raise ValueError(f"all {key} tensors must have the same shape")
        collated[key] = torch.stack([item[key] for item in batch], dim=0)
    collated["metadata"] = [item["metadata"] for item in batch]
    return collated


def build_stgnn_dataloader(
    samples_or_root: Sequence[StgnnTensorSample] | Path,
    *,
    split: str | None = None,
    batch_size: int = 32,
    shuffle: bool = False,
    num_workers: int = 0,
) -> Any:
    _require_torch()
    dataset = StgnnTorchDataset(samples_or_root, split=split)
    return torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        collate_fn=stgnn_collate_fn,
    )


def _require_torch() -> None:
    if torch is None:
        raise ImportError(
            "PyTorch is required for backend.app.training.torch_dataset; "
            "install torch to use StgnnTorchDataset or DataLoader helpers."
        )


__all__ = [
    "TORCH_AVAILABLE",
    "StgnnTorchDataset",
    "stgnn_collate_fn",
    "build_stgnn_dataloader",
]
