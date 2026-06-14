from __future__ import annotations

import numpy as np
import pytest

from backend.app.schemas.training import (
    StgnnSampleMetadata,
    StgnnTensorSample,
    default_stgnn_feature_spec,
    feature_spec_hash,
)


def test_core_converter_imports_without_torch() -> None:
    import backend.app.training.converter as converter

    assert converter.StgnnDatasetConverter is not None


def test_torch_dataset_module_imports_without_torch_and_constructor_reports_error() -> None:
    from backend.app.training import torch_dataset

    assert torch_dataset.StgnnTorchDataset is not None
    if not torch_dataset.TORCH_AVAILABLE:
        with pytest.raises(ImportError, match="PyTorch is required"):
            torch_dataset.StgnnTorchDataset([])


def test_torch_dataset_len_getitem_collate_and_dataloader() -> None:
    torch = pytest.importorskip("torch")
    from backend.app.training.torch_dataset import (
        StgnnTorchDataset,
        build_stgnn_dataloader,
        stgnn_collate_fn,
    )

    samples = [_sample("train", 0), _sample("train", 1), _sample("val", 2)]
    dataset = StgnnTorchDataset(samples, split="train")

    assert len(dataset) == 2
    item = dataset[0]
    assert item["X_node"].dtype == torch.float32
    assert item["node_mask"].dtype == torch.bool
    assert item["metadata"]["split"] == "train"

    batch = stgnn_collate_fn([dataset[0], dataset[1]])
    assert batch["X_node"].shape[0] == 2
    assert batch["Y_risk"].shape[0] == 2
    assert isinstance(batch["metadata"], list)
    assert batch["metadata"][0]["start_frame"] == 0

    loader = build_stgnn_dataloader(samples, split="train", batch_size=2, shuffle=False)
    loader_batch = next(iter(loader))
    assert loader_batch["X_node"].shape[0] == 2


def test_torch_collate_rejects_inconsistent_shapes() -> None:
    pytest.importorskip("torch")
    from backend.app.training.torch_dataset import StgnnTorchDataset, stgnn_collate_fn

    left = StgnnTorchDataset([_sample("train", 0)])[0]
    right = StgnnTorchDataset([_sample("train", 1, max_nodes=3)])[0]

    with pytest.raises(ValueError):
        stgnn_collate_fn([left, right])


def _sample(split: str, start_frame: int, *, max_nodes: int = 2) -> StgnnTensorSample:
    spec = default_stgnn_feature_spec(max_nodes=max_nodes, risk_label_horizons_s=[5.0])
    metadata = StgnnSampleMetadata(
        dataset_id="dataset-a",
        split=split,
        episode_id=f"E-{split}",
        start_frame=start_frame,
        input_steps=2,
        pred_steps=2,
        stride_steps=1,
        risk_label_horizons_s=[5.0],
        source_paths={"trajectories": "trajectories.parquet"},
        source_window_index={"row": start_frame},
        feature_spec_hash=feature_spec_hash(spec),
    )
    return StgnnTensorSample(
        metadata=metadata,
        feature_spec=spec,
        X_node=np.zeros((2, max_nodes, len(spec.node_features))),
        X_edge=np.zeros((2, max_nodes, max_nodes, len(spec.edge_features))),
        A_phy=np.zeros((2, max_nodes, max_nodes)),
        Y_traj=np.zeros((2, max_nodes, len(spec.traj_targets))),
        Y_risk=np.zeros((1, max_nodes, max_nodes, len(spec.risk_targets))),
        node_mask=np.array([True] * max_nodes),
        edge_mask=np.zeros((max_nodes, max_nodes), dtype=bool),
        risk_mask=np.zeros((1, max_nodes, max_nodes), dtype=bool),
    )
