from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.schemas.dataset import (
    DATASET_E_QUALITY_FAILED,
    DatasetBuildError,
    DatasetBuildOptions,
)
from backend.app.tests.test_dataset_builder import _builder, _config, _episode


def test_dataset_builder_can_fail_fast_on_quality_errors(tmp_path: Path) -> None:
    source_root = tmp_path / "runs"
    _episode(source_root, "E001")
    _episode(source_root, "E002", failed=True)
    config = _config()

    with pytest.raises(DatasetBuildError) as exc_info:
        _builder(config).build(
            config=config,
            options=DatasetBuildOptions(
                source_roots=[source_root],
                output_root=tmp_path / "datasets",
                fail_on_quality_error=True,
            ),
        )

    assert exc_info.value.code == DATASET_E_QUALITY_FAILED
    assert exc_info.value.details["failed_episode_ids"] == ["E002"]
    assert not (
        tmp_path
        / "datasets"
        / config.dataset_id
        / "metadata"
        / "dataset_manifest.json"
    ).exists()
