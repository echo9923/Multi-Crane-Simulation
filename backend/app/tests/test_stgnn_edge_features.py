from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SOURCE_MISSING,
    TRAINING_E_TIME_LEAKAGE,
    StgnnFeatureSpec,
    TrainingConversionError,
    default_stgnn_feature_spec,
)
from backend.app.training.edge_features import EdgeFeatureBuilder
from backend.app.training.episode_source import EpisodeTables


def test_edge_feature_builder_outputs_directed_edges_adjacency_and_mask() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    X_edge, A_phy, edge_mask = EdgeFeatureBuilder(feature_spec=spec).build(
        window=_window(),
        tables=_tables(),
        crane_order=["C1", "C2", "C3"],
        max_nodes=4,
    )

    c12_feature = X_edge[0, 0, 1, :]
    c21_feature = X_edge[0, 1, 0, :]
    assert X_edge.shape == (2, 4, 4, len(spec.edge_features))
    assert A_phy.shape == (2, 4, 4)
    assert edge_mask[0, 1]
    assert edge_mask[1, 0]
    assert not edge_mask[0, 0]
    assert not edge_mask[0, 3]
    assert A_phy[0, 0, 1] == pytest.approx(0.7)
    assert X_edge[0, 0, 1, spec.edge_features.index("edge_distance_m")] == pytest.approx(10.0)
    assert c12_feature[spec.edge_features.index("edge_delta_theta_rad")] == pytest.approx(0.25)
    assert c21_feature[spec.edge_features.index("clearance_min_now_m")] == pytest.approx(4.0)
    assert np.isfinite(X_edge).all()
    assert not X_edge[:, 3, :, :].any()
    assert not A_phy[:, 3, :].any()


def test_edge_feature_builder_uses_distance_adjacency_fallback_without_weight() -> None:
    spec = default_stgnn_feature_spec(max_nodes=2, risk_label_horizons_s=[5.0])
    graph_rows = [_graph_row(frame=0, src="C1", dst="C2", weight=None, distance=9.0)]
    graph_rows += [_graph_row(frame=1, src="C1", dst="C2", weight=None, distance=4.0)]
    X_edge, A_phy, _ = EdgeFeatureBuilder(feature_spec=spec).build(
        window=_window(num_cranes=2),
        tables=_tables(cranes=["C1", "C2"], graph_rows=graph_rows),
        crane_order=["C1", "C2"],
        max_nodes=2,
    )

    assert A_phy[0, 0, 1] == pytest.approx(0.1)
    assert A_phy[1, 0, 1] == pytest.approx(0.2)
    assert X_edge[0, 0, 1, spec.edge_features.index("edge_overlap_ratio")] == 0.0


def test_edge_feature_builder_uses_pair_risks_when_graph_edges_missing_with_fallback() -> None:
    spec = default_stgnn_feature_spec(max_nodes=2, risk_label_horizons_s=[5.0])
    X_edge, A_phy, edge_mask = EdgeFeatureBuilder(
        feature_spec=spec,
        allow_graph_edge_fallback=True,
    ).build(
        window=_window(num_cranes=2),
        tables=_tables(cranes=["C1", "C2"], graph_rows=None),
        crane_order=["C1", "C2"],
        max_nodes=2,
    )

    assert edge_mask[0, 1]
    assert X_edge[0, 0, 1, spec.edge_features.index("clearance_min_now_m")] == pytest.approx(4.0)
    assert X_edge[0, 1, 0, spec.edge_features.index("clearance_min_now_m")] == pytest.approx(4.0)
    assert A_phy[0, 0, 1] == pytest.approx(1.0 / 7.0)


def test_edge_feature_builder_rejects_missing_graph_edges_without_fallback() -> None:
    with pytest.raises(TrainingConversionError) as exc_info:
        EdgeFeatureBuilder(feature_spec=default_stgnn_feature_spec(max_nodes=2, risk_label_horizons_s=[5.0])).build(
            window=_window(num_cranes=2),
            tables=_tables(cranes=["C1", "C2"], graph_rows=None),
            crane_order=["C1", "C2"],
            max_nodes=2,
        )

    assert exc_info.value.code == TRAINING_E_SOURCE_MISSING


def test_edge_feature_builder_rejects_future_label_edge_feature() -> None:
    spec = StgnnFeatureSpec(
        node_features=["theta_sin"],
        edge_features=["edge_distance_m", "risk_level_5s"],
        traj_targets=["hook_x"],
        risk_targets=["collision_label"],
        risk_label_horizons_s=[5.0],
        max_nodes=2,
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        EdgeFeatureBuilder(feature_spec=spec).build(
            window=_window(num_cranes=2),
            tables=_tables(cranes=["C1", "C2"]),
            crane_order=["C1", "C2"],
            max_nodes=2,
        )

    assert exc_info.value.code == TRAINING_E_TIME_LEAKAGE


def test_single_crane_edge_features_are_empty() -> None:
    spec = default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])
    X_edge, A_phy, edge_mask = EdgeFeatureBuilder(
        feature_spec=spec,
        allow_graph_edge_fallback=True,
    ).build(
        window=_window(num_cranes=1),
        tables=_tables(cranes=["C1"], pair_rows=[], graph_rows=None),
        crane_order=["C1"],
        max_nodes=3,
    )

    assert X_edge.shape == (2, 3, 3, len(spec.edge_features))
    assert not X_edge.any()
    assert not A_phy.any()
    assert not edge_mask.any()


def _window(*, num_cranes: int = 3) -> DatasetWindowIndexRow:
    return DatasetWindowIndexRow(
        dataset_id="dataset-a",
        split="train",
        episode_id="E001",
        start_frame=0,
        input_steps=2,
        pred_steps=1,
        stride_steps=1,
        input_start_time_s=0.0,
        prediction_end_time_s=1.5,
        num_cranes=num_cranes,
        label_horizons_s=[5.0],
        source_paths={"graph_edges": "graph_edges.parquet"},
    )


def _tables(
    *,
    cranes: list[str] | None = None,
    graph_rows: list[dict] | None | object = ...,
    pair_rows: list[dict] | None = None,
) -> EpisodeTables:
    cranes = cranes or ["C1", "C2", "C3"]
    if graph_rows is ...:
        graph_rows = [
            _graph_row(frame=0, src="C1", dst="C2", weight=0.7, distance=10.0, delta_theta=0.25),
            _graph_row(frame=0, src="C2", dst="C1", weight=0.5, distance=11.0, delta_theta=-0.25),
            _graph_row(frame=1, src="C1", dst="C2", weight=0.6, distance=9999.0, delta_theta=0.3),
            _graph_row(frame=2, src="C1", dst="C2", weight=1.0, distance=9999.0, delta_theta=99.0),
        ]
    if pair_rows is None:
        pair_rows = [
            _pair_row(frame=0, i="C1", j="C2", clearance=4.0),
            _pair_row(frame=1, i="C1", j="C2", clearance=3.0),
            _pair_row(frame=2, i="C1", j="C2", clearance=9999.0),
        ]
    return EpisodeTables(
        episode_id="E001",
        scenario_id=None,
        trajectories=pa.Table.from_pylist(
            [
                {
                    "schema_version": "1.0",
                    "episode_id": "E001",
                    "frame": frame,
                    "time_s": float(frame),
                    "crane_id": crane,
                }
                for frame in range(3)
                for crane in cranes
            ]
        ),
        pair_risks=pa.Table.from_pylist(pair_rows),
        graph_edges=None if graph_rows is None else pa.Table.from_pylist(graph_rows),
        tasks=None,
        episode_summary={"episode_id": "E001"},
        episode_manifest={"episode_id": "E001"},
        source_paths={},
    )


def _graph_row(
    *,
    frame: int,
    src: str,
    dst: str,
    weight: float | None,
    distance: float,
    delta_theta: float = 0.0,
) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "frame": frame,
        "time_s": float(frame),
        "src_crane_id": src,
        "dst_crane_id": dst,
        "edge_distance_m": distance,
        "edge_overlap_ratio": None,
        "edge_delta_height_m": 1.0,
        "edge_delta_theta_rad": delta_theta,
        "edge_delta_theta_dot_rad_s": 0.1,
        "edge_ttc_s": None,
        "edge_risk_level": "safe",
        "edge_weight_physics_prior": weight,
    }


def _pair_row(*, frame: int, i: str, j: str, clearance: float) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "frame": frame,
        "time_s": float(frame),
        "crane_i": i,
        "crane_j": j,
        "distance_min_raw_now_m": clearance + 2.0,
        "clearance_min_now_m": clearance,
        "risk_level_now": "safe",
    }
