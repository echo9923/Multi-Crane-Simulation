from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from backend.app.schemas.dataset import (
    DatasetBuildOptions,
    DatasetEpisodeRecord,
    DatasetFileRecord,
    DatasetManifest,
    DatasetQualityReport,
    DatasetSplitManifest,
    DatasetSummary,
    DatasetWindowIndexRow,
    assert_no_secret_payload,
)
from backend.app.tests.test_dataset_builder import _builder, _config, _episode


def test_dataset_artifacts_round_trip_through_public_schemas(tmp_path: Path) -> None:
    source_root = tmp_path / "runs"
    _episode(source_root, "E001", high=True)
    _episode(source_root, "E002")
    _episode(source_root, "E003", failed=True)
    config = _config()

    result = _builder(config).build(
        config=config,
        options=DatasetBuildOptions(
            source_roots=[source_root],
            output_root=tmp_path / "datasets",
        ),
    )

    metadata_dir = result.dataset_dir / "metadata"
    manifest = DatasetManifest.model_validate(
        json.loads((metadata_dir / "dataset_manifest.json").read_text())
    )
    summary = DatasetSummary.model_validate(
        json.loads((metadata_dir / "dataset_summary.json").read_text())
    )
    quality_summary = json.loads((metadata_dir / "quality_summary.json").read_text())
    split_manifest = json.loads((metadata_dir / "split_manifest.json").read_text())

    assert manifest.dataset_id == summary.dataset_id == config.dataset_id
    assert summary.num_quarantined == 1
    assert_no_secret_payload(manifest.model_dump(mode="json"), context="manifest")
    assert_no_secret_payload(summary.model_dump(mode="json"), context="summary")
    for report in quality_summary["reports"]:
        DatasetQualityReport.model_validate(report)

    episodes = [
        DatasetEpisodeRecord.model_validate(row)
        for row in pq.read_table(result.dataset_dir / "index" / "episodes.parquet").to_pylist()
    ]
    windows = [
        DatasetWindowIndexRow.model_validate(row)
        for row in pq.read_table(result.dataset_dir / "index" / "windows.parquet").to_pylist()
    ]
    files = [
        DatasetFileRecord.model_validate(row)
        for row in pq.read_table(result.dataset_dir / "index" / "files.parquet").to_pylist()
    ]
    split_contract = DatasetSplitManifest.model_validate(split_manifest)

    assert {episode.episode_id for episode in episodes} == {"E001", "E002"}
    assert {window.episode_id for window in windows} <= {"E001", "E002"}
    assert all(file_record.copy_mode == "index_only" for file_record in files)
    assert {assignment.episode_id for assignment in split_contract.assignments} == {
        "E001",
        "E002",
    }


def test_split_jsonl_files_match_split_manifest_assignments(tmp_path: Path) -> None:
    source_root = tmp_path / "runs"
    _episode(source_root, "E001", high=True)
    _episode(source_root, "E002")
    config = _config()

    result = _builder(config).build(
        config=config,
        options=DatasetBuildOptions(
            source_roots=[source_root],
            output_root=tmp_path / "datasets",
        ),
    )

    manifest = json.loads(
        (result.dataset_dir / "metadata" / "split_manifest.json").read_text()
    )
    expected = {
        (assignment["split"], assignment["episode_id"])
        for assignment in manifest["assignments"]
    }
    observed: set[tuple[str, str]] = set()
    for split_dir in (result.dataset_dir / "splits").iterdir():
        split_file = split_dir / "episodes.jsonl"
        if not split_file.is_file():
            continue
        for line in split_file.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            observed.add((payload["split"], payload["episode_id"]))

    assert observed == expected
