from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    StgnnFeatureSpec,
    TrainingConversionError,
)
from backend.app.training.episode_source import EpisodeTables
from backend.app.training.leakage import LeakageGuard
from backend.app.training.variable_nodes import VariableNodeStrategy

TASK_STAGE_CODES = {
    "idle": 0.0,
    "move_to_pickup": 1.0,
    "attach": 2.0,
    "move_to_dropoff": 3.0,
    "release": 4.0,
    "completed": 5.0,
}
VISIBILITY_CODES = {
    "unknown": 0.0,
    "clear": 1.0,
    "good": 1.0,
    "medium": 2.0,
    "poor": 3.0,
    "low": 3.0,
}
_DERIVED_FEATURES = {
    "task_stage_code",
    "has_task",
    "wind_direction_sin",
    "wind_direction_cos",
    "visibility_code",
}


class NodeFeatureBuilder:
    def __init__(self, *, feature_spec: StgnnFeatureSpec) -> None:
        self.feature_spec = feature_spec
        self._guard = LeakageGuard()
        self._nodes = VariableNodeStrategy()

    def build(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        self._guard.validate_feature_names(
            self.feature_spec.node_features,
            kind="node",
        )
        self._validate_required_columns(tables)
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

        rows_by_key = {
            (int(row["frame"]), str(row["crane_id"])): row
            for row in tables.trajectories.to_pylist()
            if window.start_frame <= int(row["frame"]) < window.start_frame + window.input_steps
        }
        X_node = np.zeros(
            (window.input_steps, max_nodes, len(self.feature_spec.node_features)),
            dtype=float,
        )
        for t_index, frame in enumerate(input_frames):
            for node_index, crane_id in enumerate(crane_order):
                row = rows_by_key.get((frame, crane_id))
                if row is None:
                    raise TrainingConversionError(
                        TRAINING_E_SOURCE_SCHEMA_INVALID,
                        "trajectory table is missing an input frame/crane row",
                        details={
                            "episode_id": window.episode_id,
                            "frame": frame,
                            "crane_id": crane_id,
                        },
                    )
                X_node[t_index, node_index, :] = [
                    _feature_value(row, feature)
                    for feature in self.feature_spec.node_features
                ]
        return X_node, self._nodes.node_mask(crane_order=crane_order, max_nodes=max_nodes)

    def _validate_required_columns(self, tables: EpisodeTables) -> None:
        raw_features = set(self.feature_spec.node_features) - _DERIVED_FEATURES
        missing = sorted(raw_features - set(tables.trajectories.column_names))
        if missing:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "trajectory table is missing node feature columns",
                details={"role": "trajectories", "missing_fields": missing},
            )


def _feature_value(row: dict, feature: str) -> float:
    if feature == "task_stage_code":
        return TASK_STAGE_CODES.get(str(row.get("task_stage") or ""), 0.0)
    if feature == "has_task":
        return 1.0 if row.get("task_id") else 0.0
    if feature == "wind_direction_sin":
        degrees = row.get("wind_direction_deg")
        if degrees is None:
            return 0.0
        return math.sin(math.radians(float(degrees)))
    if feature == "wind_direction_cos":
        degrees = row.get("wind_direction_deg")
        if degrees is None:
            return 1.0
        return math.cos(math.radians(float(degrees)))
    if feature == "visibility_code":
        return VISIBILITY_CODES.get(str(row.get("visibility_level") or "unknown"), 0.0)
    value = row.get(feature)
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


__all__ = ["NodeFeatureBuilder", "TASK_STAGE_CODES", "VISIBILITY_CODES"]
