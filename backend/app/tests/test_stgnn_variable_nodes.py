from __future__ import annotations

import pyarrow as pa
import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_VARIABLE_NODES_UNSUPPORTED,
    TrainingConversionError,
)
from backend.app.training.episode_source import EpisodeTables
from backend.app.training.variable_nodes import VariableNodePlan, VariableNodeStrategy


def test_variable_node_plan_uses_global_max_without_resplitting() -> None:
    windows = [
        _window("E-two", split="train", num_cranes=2),
        _window("E-four", split="val", num_cranes=4),
    ]
    plan = VariableNodeStrategy().plan(
        windows=windows,
        episode_cranes={
            "E-two": ["crane_2", "crane_10"],
            "E-four": ["A", "B", "C", "D"],
        },
    )

    assert isinstance(plan, VariableNodePlan)
    assert plan.strategy == "pad_and_mask"
    assert plan.max_nodes == 4
    assert plan.crane_order_by_episode["E-two"] == ["crane_10", "crane_2"]
    assert [window.split for window in windows] == ["train", "val"]


def test_variable_node_plan_rejects_configured_max_nodes_too_small() -> None:
    with pytest.raises(TrainingConversionError) as exc_info:
        VariableNodeStrategy().plan(
            windows=[_window("E-four", num_cranes=4)],
            episode_cranes={"E-four": ["A", "B", "C", "D"]},
            configured_max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_VARIABLE_NODES_UNSUPPORTED
    assert exc_info.value.details["max_observed_nodes"] == 4


def test_crane_order_for_window_reads_sorted_trajectory_cranes() -> None:
    strategy = VariableNodeStrategy()
    window = _window("E001", num_cranes=3)
    tables = _tables("E001", ["crane_2", "crane_10", "crane_1"])

    assert strategy.crane_order_for_window(window=window, tables=tables) == [
        "crane_1",
        "crane_10",
        "crane_2",
    ]
    assert strategy.crane_order_for_window(window=window, tables=tables) == [
        "crane_1",
        "crane_10",
        "crane_2",
    ]


def test_crane_order_rejects_window_num_cranes_mismatch() -> None:
    with pytest.raises(TrainingConversionError) as exc_info:
        VariableNodeStrategy().crane_order_for_window(
            window=_window("E001", num_cranes=2),
            tables=_tables("E001", ["C1", "C2", "C3"]),
        )

    assert exc_info.value.code == TRAINING_E_VARIABLE_NODES_UNSUPPORTED
    assert exc_info.value.details["expected"] == 2
    assert exc_info.value.details["actual"] == 3


def test_node_and_edge_masks_mark_padding_and_self_edges() -> None:
    strategy = VariableNodeStrategy()
    node_mask = strategy.node_mask(crane_order=["C1", "C2"], max_nodes=4)
    edge_mask = strategy.edge_mask(crane_order=["C1", "C2"], max_nodes=4)

    assert node_mask.tolist() == [True, True, False, False]
    assert edge_mask.shape == (4, 4)
    assert edge_mask[0, 1]
    assert edge_mask[1, 0]
    assert not edge_mask[0, 0]
    assert not edge_mask[2, 0]
    assert not edge_mask[0, 2]


def test_single_crane_edge_mask_is_all_false() -> None:
    edge_mask = VariableNodeStrategy().edge_mask(crane_order=["C1"], max_nodes=3)

    assert edge_mask.shape == (3, 3)
    assert not edge_mask.any()


def _window(
    episode_id: str,
    *,
    split: str = "train",
    num_cranes: int,
) -> DatasetWindowIndexRow:
    return DatasetWindowIndexRow(
        dataset_id="dataset-a",
        split=split,
        episode_id=episode_id,
        start_frame=0,
        input_steps=2,
        pred_steps=2,
        stride_steps=1,
        input_start_time_s=0.0,
        prediction_end_time_s=2.0,
        num_cranes=num_cranes,
        label_horizons_s=[5.0],
        source_paths={"trajectories": "trajectories.parquet"},
    )


def _tables(episode_id: str, cranes: list[str]) -> EpisodeTables:
    rows = [
        {
            "schema_version": "1.0",
            "episode_id": episode_id,
            "frame": frame,
            "time_s": float(frame),
            "crane_id": crane,
        }
        for frame in range(2)
        for crane in cranes
    ]
    return EpisodeTables(
        episode_id=episode_id,
        scenario_id=None,
        trajectories=pa.Table.from_pylist(rows),
        pair_risks=pa.Table.from_pylist([]),
        graph_edges=None,
        tasks=None,
        episode_summary={"episode_id": episode_id},
        episode_manifest={"episode_id": episode_id},
        source_paths={},
    )
