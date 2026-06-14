from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    StgnnConversionSummary,
    StgnnFeatureSpec,
    StgnnSampleIndexRow,
    StgnnSampleMetadata,
    assert_no_training_secret,
    feature_spec_hash,
)


class SampleMetadataBuilder:
    def build(
        self,
        *,
        window: DatasetWindowIndexRow,
        feature_spec: StgnnFeatureSpec,
        source_paths: Mapping[str, Path],
        crane_order: Sequence[str],
    ) -> StgnnSampleMetadata:
        source_path_payload = {
            role: str(path)
            for role, path in sorted(source_paths.items())
        }
        assert_no_training_secret(source_path_payload, context="sample_source_paths")
        metadata = StgnnSampleMetadata(
            dataset_id=window.dataset_id,
            split=window.split,
            scenario_id=window.scenario_id,
            episode_id=window.episode_id,
            start_frame=window.start_frame,
            input_steps=window.input_steps,
            pred_steps=window.pred_steps,
            stride_steps=window.stride_steps,
            risk_label_horizons_s=list(window.label_horizons_s),
            source_paths=source_path_payload,
            source_window_index={
                "dataset_id": window.dataset_id,
                "split": window.split,
                "episode_id": window.episode_id,
                "start_frame": window.start_frame,
                "input_steps": window.input_steps,
                "pred_steps": window.pred_steps,
                "stride_steps": window.stride_steps,
                "num_cranes": window.num_cranes,
                "crane_order": list(crane_order),
            },
            feature_spec_hash=feature_spec_hash(feature_spec),
        )
        assert_no_training_secret(metadata.model_dump(mode="json"), context="sample_metadata")
        return metadata

    def sample_id(self, metadata: StgnnSampleMetadata) -> str:
        payload = {
            "dataset_id": metadata.dataset_id,
            "split": metadata.split,
            "episode_id": metadata.episode_id,
            "start_frame": metadata.start_frame,
            "input_steps": metadata.input_steps,
            "pred_steps": metadata.pred_steps,
            "feature_spec_hash": metadata.feature_spec_hash,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ConversionSummaryBuilder:
    def build(
        self,
        *,
        dataset_id: str,
        samples: Sequence[StgnnSampleIndexRow],
        feature_spec: StgnnFeatureSpec,
        skipped_counts: Mapping[str, int] | None = None,
        risk_distribution: Mapping[str, float] | None = None,
        warnings: Sequence[dict[str, Any]] = (),
    ) -> StgnnConversionSummary:
        warnings_payload = [dict(warning) for warning in warnings]
        assert_no_training_secret(warnings_payload, context="conversion_warnings")
        sample_counts = Counter(sample.split for sample in samples)
        episode_ids = {sample.episode_id for sample in samples}
        return StgnnConversionSummary(
            dataset_id=dataset_id,
            sample_counts=dict(sorted(sample_counts.items())),
            skipped_counts=dict(sorted((skipped_counts or {}).items())),
            num_episodes=len(episode_ids),
            max_nodes=feature_spec.max_nodes,
            feature_spec=feature_spec,
            risk_distribution=dict(sorted((risk_distribution or {}).items())),
            warnings=warnings_payload,
        )


def build_sample_index_row(
    *,
    metadata: StgnnSampleMetadata,
    feature_spec: StgnnFeatureSpec,
    num_nodes: int,
    tensor_path: Path | None = None,
    tensor_offset: int | None = None,
) -> StgnnSampleIndexRow:
    sample_id = SampleMetadataBuilder().sample_id(metadata)
    return StgnnSampleIndexRow(
        sample_id=sample_id,
        dataset_id=metadata.dataset_id,
        split=metadata.split,
        episode_id=metadata.episode_id,
        scenario_id=metadata.scenario_id,
        start_frame=metadata.start_frame,
        tensor_path=str(tensor_path) if tensor_path is not None else None,
        tensor_offset=tensor_offset,
        num_nodes=num_nodes,
        max_nodes=feature_spec.max_nodes,
        input_steps=metadata.input_steps,
        pred_steps=metadata.pred_steps,
        node_feature_dim=len(feature_spec.node_features),
        edge_feature_dim=len(feature_spec.edge_features),
        traj_target_dim=len(feature_spec.traj_targets),
        risk_target_dim=len(feature_spec.risk_targets),
        metadata_json=metadata.model_dump(mode="json"),
    )


__all__ = [
    "SampleMetadataBuilder",
    "ConversionSummaryBuilder",
    "build_sample_index_row",
]
