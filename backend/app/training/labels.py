from __future__ import annotations

from typing import Sequence

import numpy as np

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_LABEL_MISSING,
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_AXIS_INVALID,
    StgnnFeatureSpec,
    TrainingConversionError,
)
from backend.app.training.episode_source import EpisodeTables
from backend.app.training.leakage import LeakageGuard

RISK_LEVEL_LABEL_CODES = {
    "safe": 0.0,
    "low": 1.0,
    "medium": 2.0,
    "high": 3.0,
    "near_miss": 4.0,
    "collision": 5.0,
}
_ALLOWED_RISK_TARGETS = {
    "risk_level_code",
    "collision_label",
    "min_clearance_future_m",
    "ttc_s",
}


class LabelBuilder:
    def __init__(self, *, feature_spec: StgnnFeatureSpec) -> None:
        self.feature_spec = feature_spec
        self._guard = LeakageGuard()

    def build_traj(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> np.ndarray:
        missing = sorted(set(self.feature_spec.traj_targets) - set(tables.trajectories.column_names))
        if missing:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "trajectory table is missing target columns",
                details={"role": "trajectories", "missing_fields": missing},
            )
        prediction_frames = list(
            range(
                window.start_frame + window.input_steps,
                window.start_frame + window.input_steps + window.pred_steps,
            )
        )
        self._guard.validate_window_ranges(
            start_frame=window.start_frame,
            input_steps=window.input_steps,
            pred_steps=window.pred_steps,
            requested_input_frames=list(range(window.start_frame, window.start_frame + window.input_steps)),
            requested_label_frames=prediction_frames,
        )
        rows_by_key = {
            (int(row["frame"]), str(row["crane_id"])): row
            for row in tables.trajectories.to_pylist()
            if int(row["frame"]) in prediction_frames
        }
        Y_traj = np.zeros(
            (window.pred_steps, max_nodes, len(self.feature_spec.traj_targets)),
            dtype=float,
        )
        for t_index, frame in enumerate(prediction_frames):
            for node_index, crane_id in enumerate(crane_order):
                row = rows_by_key.get((frame, crane_id))
                if row is None:
                    raise TrainingConversionError(
                        TRAINING_E_TIME_AXIS_INVALID,
                        "trajectory table is missing a prediction frame/crane row",
                        details={
                            "episode_id": window.episode_id,
                            "frame": frame,
                            "crane_id": crane_id,
                        },
                    )
                Y_traj[t_index, node_index, :] = [
                    _numeric_value(row.get(target))
                    for target in self.feature_spec.traj_targets
                ]
        return Y_traj

    def build_risk(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        unsupported = sorted(set(self.feature_spec.risk_targets) - _ALLOWED_RISK_TARGETS)
        if unsupported:
            raise TrainingConversionError(
                TRAINING_E_LABEL_MISSING,
                "unsupported risk target requested",
                details={"unsupported_targets": unsupported},
            )
        required = _required_horizon_fields(self.feature_spec.risk_label_horizons_s)
        missing = sorted(required - set(tables.pair_risks.column_names))
        if missing and not (window.num_cranes <= 1 and tables.pair_risks.num_rows == 0):
            raise TrainingConversionError(
                TRAINING_E_LABEL_MISSING,
                "pair_risks table is missing offline label columns",
                details={"role": "pair_risks", "missing_fields": missing},
            )
        anchor_frame = window.start_frame + window.input_steps - 1
        self._guard.validate_risk_anchor_frame(
            start_frame=window.start_frame,
            input_steps=window.input_steps,
            anchor_frame=anchor_frame,
        )
        node_index = {crane_id: index for index, crane_id in enumerate(crane_order)}
        horizons = self.feature_spec.risk_label_horizons_s
        Y_risk = np.zeros(
            (len(horizons), max_nodes, max_nodes, len(self.feature_spec.risk_targets)),
            dtype=float,
        )
        risk_mask = np.zeros((len(horizons), max_nodes, max_nodes), dtype=bool)
        for row in tables.pair_risks.to_pylist():
            if row.get("frame") != anchor_frame:
                continue
            left = row.get("crane_i")
            right = row.get("crane_j")
            if left not in node_index or right not in node_index:
                continue
            for h_index, horizon in enumerate(horizons):
                suffix = _horizon_suffix(horizon)
                values = [
                    _risk_target_value(row, target, suffix)
                    for target in self.feature_spec.risk_targets
                ]
                for src, dst in ((left, right), (right, left)):
                    src_index = node_index[src]
                    dst_index = node_index[dst]
                    Y_risk[h_index, src_index, dst_index, :] = values
                    risk_mask[h_index, src_index, dst_index] = True
        return Y_risk, risk_mask


def _risk_target_value(row: dict, target: str, suffix: str) -> float:
    if target == "risk_level_code":
        value = row.get(f"risk_level_{suffix}")
        if value not in RISK_LEVEL_LABEL_CODES:
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "risk level label is invalid",
                details={"field": f"risk_level_{suffix}", "value": value},
            )
        return RISK_LEVEL_LABEL_CODES[str(value)]
    if target == "collision_label":
        field = f"collision_label_{suffix}"
        value = row.get(field)
        if value not in (0, 1):
            raise TrainingConversionError(
                TRAINING_E_SOURCE_SCHEMA_INVALID,
                "collision label must be 0 or 1",
                details={"field": field, "value": value},
            )
        return float(value)
    if target == "min_clearance_future_m":
        return _numeric_value(row.get(f"min_clearance_future_{suffix}_m"))
    if target == "ttc_s":
        value = row.get(f"ttc_{suffix}_s")
        return -1.0 if value is None else float(value)
    raise TrainingConversionError(
        TRAINING_E_LABEL_MISSING,
        "unsupported risk target requested",
        details={"target": target},
    )


def _numeric_value(value: object) -> float:
    if value is None:
        return 0.0
    return float(value)


def _required_horizon_fields(horizons_s: list[float]) -> set[str]:
    fields: set[str] = set()
    for horizon in horizons_s:
        suffix = _horizon_suffix(horizon)
        fields.update(
            {
                f"risk_level_{suffix}",
                f"collision_label_{suffix}",
                f"min_clearance_future_{suffix}_m",
                f"ttc_{suffix}_s",
            }
        )
    return fields


def _horizon_suffix(horizon: float) -> str:
    if horizon.is_integer():
        return f"{int(horizon)}s"
    return f"{horizon:g}s"


__all__ = ["LabelBuilder", "RISK_LEVEL_LABEL_CODES"]
