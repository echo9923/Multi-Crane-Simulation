from __future__ import annotations

from typing import Sequence

import numpy as np

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SOURCE_MISSING,
    StgnnFeatureSpec,
    TrainingConversionError,
)
from backend.app.training.episode_source import EpisodeTables
from backend.app.training.leakage import LeakageGuard
from backend.app.training.variable_nodes import VariableNodeStrategy

RISK_LEVEL_NOW_CODES = {
    "safe": 0.0,
    "low": 1.0,
    "medium": 2.0,
    "high": 3.0,
    "near_miss": 4.0,
    "collision": 5.0,
}


class EdgeFeatureBuilder:
    def __init__(
        self,
        *,
        feature_spec: StgnnFeatureSpec,
        allow_graph_edge_fallback: bool = False,
    ) -> None:
        self.feature_spec = feature_spec
        self.allow_graph_edge_fallback = allow_graph_edge_fallback
        self._guard = LeakageGuard()
        self._nodes = VariableNodeStrategy()

    def build(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        self._guard.validate_feature_names(
            self.feature_spec.edge_features,
            kind="edge",
        )
        input_frames = list(range(window.start_frame, window.start_frame + window.input_steps))
        self._guard.validate_window_ranges(
            start_frame=window.start_frame,
            input_steps=window.input_steps,
            pred_steps=window.pred_steps,
            requested_input_frames=input_frames,
            requested_label_frames=list(
                range(
                    window.start_frame + window.input_steps,
                    window.start_frame + window.input_steps + window.pred_steps,
                )
            ),
        )
        if tables.graph_edges is None and not self.allow_graph_edge_fallback and window.num_cranes > 1:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_MISSING,
                "graph_edges are required for edge features unless fallback is enabled",
                details={"role": "graph_edges", "episode_id": window.episode_id},
            )

        node_index = {crane_id: index for index, crane_id in enumerate(crane_order)}
        X_edge = np.zeros(
            (
                window.input_steps,
                max_nodes,
                max_nodes,
                len(self.feature_spec.edge_features),
            ),
            dtype=float,
        )
        A_phy = np.zeros((window.input_steps, max_nodes, max_nodes), dtype=float)
        pair_rows = _pair_rows_by_frame(tables)

        if tables.graph_edges is not None:
            for row in tables.graph_edges.to_pylist():
                frame = int(row["frame"])
                if frame not in input_frames:
                    continue
                src = row["src_crane_id"]
                dst = row["dst_crane_id"]
                if src not in node_index or dst not in node_index or src == dst:
                    continue
                t_index = frame - window.start_frame
                src_index = node_index[src]
                dst_index = node_index[dst]
                merged = dict(row)
                merged.update(_pair_context(pair_rows, frame=frame, src=src, dst=dst))
                X_edge[t_index, src_index, dst_index, :] = [
                    _edge_feature_value(merged, feature)
                    for feature in self.feature_spec.edge_features
                ]
                A_phy[t_index, src_index, dst_index] = _adjacency_weight(merged)

        if tables.graph_edges is None or self.allow_graph_edge_fallback:
            for frame in input_frames:
                for row in pair_rows.get(frame, []):
                    left = row["crane_i"]
                    right = row["crane_j"]
                    if left not in node_index or right not in node_index:
                        continue
                    for src, dst in ((left, right), (right, left)):
                        t_index = frame - window.start_frame
                        src_index = node_index[src]
                        dst_index = node_index[dst]
                        if not X_edge[t_index, src_index, dst_index, :].any():
                            X_edge[t_index, src_index, dst_index, :] = [
                                _edge_feature_value(row, feature)
                                for feature in self.feature_spec.edge_features
                            ]
                        if A_phy[t_index, src_index, dst_index] == 0:
                            A_phy[t_index, src_index, dst_index] = _adjacency_weight(row)

        edge_mask = self._nodes.edge_mask(crane_order=crane_order, max_nodes=max_nodes)
        return X_edge, A_phy, edge_mask


def _pair_rows_by_frame(tables: EpisodeTables) -> dict[int, list[dict]]:
    rows: dict[int, list[dict]] = {}
    for row in tables.pair_risks.to_pylist():
        rows.setdefault(int(row["frame"]), []).append(row)
    return rows


def _pair_context(
    pair_rows: dict[int, list[dict]],
    *,
    frame: int,
    src: str,
    dst: str,
) -> dict:
    for row in pair_rows.get(frame, []):
        if {row.get("crane_i"), row.get("crane_j")} == {src, dst}:
            return {
                "clearance_min_now_m": row.get("clearance_min_now_m"),
                "risk_level_now": row.get("risk_level_now"),
                "distance_min_raw_now_m": row.get("distance_min_raw_now_m"),
            }
    return {}


def _edge_feature_value(row: dict, feature: str) -> float:
    if feature == "risk_level_now_code":
        return RISK_LEVEL_NOW_CODES.get(str(row.get("risk_level_now") or "safe"), 0.0)
    value = row.get(feature)
    if value is None:
        return 0.0
    return float(value)


def _adjacency_weight(row: dict) -> float:
    weight = row.get("edge_weight_physics_prior")
    if weight is not None:
        value = float(weight)
        return max(0.0, min(1.0, value))
    distance = row.get("edge_distance_m")
    if distance is None:
        distance = row.get("distance_min_raw_now_m")
    if distance is not None:
        return 1.0 / (1.0 + max(float(distance), 0.0))
    clearance = row.get("clearance_min_now_m")
    if clearance is not None:
        return 1.0 / (1.0 + max(float(clearance), 0.0))
    return 0.0


__all__ = ["EdgeFeatureBuilder", "RISK_LEVEL_NOW_CODES"]
