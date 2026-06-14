from __future__ import annotations

import re
from typing import Sequence

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_AXIS_INVALID,
    TRAINING_E_TIME_LEAKAGE,
    StgnnSampleMetadata,
    TrainingConversionError,
)

FORBIDDEN_INPUT_FIELD_PATTERNS = (
    r"^min_clearance_future_",
    r"^ttc_\d",
    r"^risk_level_\d",
    r"^collision_label_",
    r"offline",
    r"future_truth",
)
_FORBIDDEN_INPUT_RES = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in FORBIDDEN_INPUT_FIELD_PATTERNS
)


class LeakageGuard:
    def validate_feature_names(self, names: Sequence[str], *, kind: str) -> None:
        for name in names:
            for pattern in _FORBIDDEN_INPUT_RES:
                if pattern.search(name):
                    raise TrainingConversionError(
                        TRAINING_E_TIME_LEAKAGE,
                        "input feature name references future or offline label data",
                        details={
                            "kind": kind,
                            "field_name": name,
                            "pattern": pattern.pattern,
                        },
                    )

    def validate_window_ranges(
        self,
        *,
        start_frame: int,
        input_steps: int,
        pred_steps: int,
        requested_input_frames: Sequence[int],
        requested_label_frames: Sequence[int],
    ) -> None:
        input_range = set(range(start_frame, start_frame + input_steps))
        label_range = list(
            range(start_frame + input_steps, start_frame + input_steps + pred_steps)
        )
        for frame in requested_input_frames:
            if frame not in input_range:
                raise TrainingConversionError(
                    TRAINING_E_TIME_LEAKAGE,
                    "input frame is outside the input window",
                    details={
                        "frame": frame,
                        "input_start_frame": start_frame,
                        "input_end_exclusive": start_frame + input_steps,
                    },
                )
        if list(requested_label_frames) != label_range:
            raise TrainingConversionError(
                TRAINING_E_TIME_AXIS_INVALID,
                "label frames must exactly match the prediction window",
                details={
                    "actual_frames": list(requested_label_frames),
                    "expected_frames": label_range,
                },
            )

    def validate_risk_anchor_frame(
        self,
        *,
        start_frame: int,
        input_steps: int,
        anchor_frame: int,
    ) -> None:
        expected = start_frame + input_steps - 1
        if anchor_frame != expected:
            raise TrainingConversionError(
                TRAINING_E_TIME_LEAKAGE,
                "risk label anchor frame must be the final input frame",
                details={
                    "actual_anchor_frame": anchor_frame,
                    "expected_anchor_frame": expected,
                },
            )

    def validate_sample_metadata(
        self,
        *,
        window: DatasetWindowIndexRow,
        metadata: StgnnSampleMetadata,
    ) -> None:
        comparisons = {
            "dataset_id": (window.dataset_id, metadata.dataset_id),
            "split": (window.split, metadata.split),
            "scenario_id": (window.scenario_id, metadata.scenario_id),
            "episode_id": (window.episode_id, metadata.episode_id),
            "start_frame": (window.start_frame, metadata.start_frame),
            "input_steps": (window.input_steps, metadata.input_steps),
            "pred_steps": (window.pred_steps, metadata.pred_steps),
            "stride_steps": (window.stride_steps, metadata.stride_steps),
            "risk_label_horizons_s": (
                window.label_horizons_s,
                metadata.risk_label_horizons_s,
            ),
        }
        for field, (expected, actual) in comparisons.items():
            if expected != actual:
                raise TrainingConversionError(
                    TRAINING_E_SOURCE_SCHEMA_INVALID,
                    "sample metadata does not match source window",
                    details={
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    },
                )


__all__ = ["FORBIDDEN_INPUT_FIELD_PATTERNS", "LeakageGuard"]
