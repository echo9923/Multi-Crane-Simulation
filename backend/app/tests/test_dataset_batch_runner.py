from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.data.batch_runner import (
    BatchEpisodeRequest,
    BatchEpisodeRunner,
    derive_episode_id,
    derive_episode_seed,
)
from backend.app.tests.test_config_schema import load_fixture
from backend.app.tests.test_config_schema import FIXTURE_DIR
from backend.app.schemas.config import DatasetConfig


class FakeEpisodeResult:
    def __init__(
        self,
        *,
        episode_id: str,
        status: str = "completed",
        final_time_s: float = 1.0,
        final_frame_index: int = 2,
    ) -> None:
        self.episode_id = episode_id
        self.status = status
        self.final_time_s = final_time_s
        self.final_frame_index = final_frame_index


class FakeRunner:
    def __init__(self, *, episode_id: str, run_dir: Path | None = None) -> None:
        self.episode_id = episode_id
        self.recorder = SimpleNamespace(run_dir=run_dir or Path("runs") / episode_id)

    def run_episode(self) -> FakeEpisodeResult:
        return FakeEpisodeResult(episode_id=self.episode_id)


def _dataset_config() -> DatasetConfig:
    raw = load_fixture("dataset_valid.yaml")
    raw["sources"] = [
        {
            "scenario_ref": str(FIXTURE_DIR / "scenario_valid.yaml"),
            "experiment_template_ref": str(FIXTURE_DIR / "experiment_valid.yaml"),
            "num_episodes": 2,
        }
    ]
    return DatasetConfig.model_validate(raw)


def test_batch_runner_generates_stable_episode_ids_and_report(tmp_path: Path) -> None:
    calls: list[dict] = []

    def runner_factory(**kwargs):
        calls.append(kwargs)
        return FakeRunner(
            episode_id=kwargs["episode_id"],
            run_dir=tmp_path / "runs" / kwargs["episode_id"],
        )

    result = BatchEpisodeRunner(runner_factory=runner_factory).run(
        BatchEpisodeRequest(
            dataset_config=_dataset_config(),
            output_root=tmp_path / "datasets",
            max_episodes=2,
        )
    )

    assert result.dataset_id == "tower_crane_llm_dataset_v1"
    assert result.requested_episodes == 2
    assert result.completed_episodes == 2
    assert result.failed_episodes == 0
    assert [call["episode_id"] for call in calls] == [
        "tower_crane_llm_dataset_v1-00-00000",
        "tower_crane_llm_dataset_v1-00-00001",
    ]
    assert calls[0]["resolved_config"].dataset["dataset_id"] == result.dataset_id
    report_path = tmp_path / "datasets" / result.dataset_id / "metadata" / "generation_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["seed_derivation"] == "hash_v1"
    assert "api_key" not in json.dumps(report)


def test_batch_runner_continues_after_episode_failure(tmp_path: Path) -> None:
    def runner_factory(**kwargs):
        if kwargs["episode_id"].endswith("00000"):
            raise RuntimeError("runner failed")
        return FakeRunner(episode_id=kwargs["episode_id"])

    result = BatchEpisodeRunner(runner_factory=runner_factory).run(
        BatchEpisodeRequest(
            dataset_config=_dataset_config(),
            output_root=tmp_path / "datasets",
            max_episodes=2,
            continue_on_episode_failure=True,
        )
    )

    assert result.completed_episodes == 1
    assert result.failed_episodes == 1
    assert result.failures[0]["episode_id"] == "tower_crane_llm_dataset_v1-00-00000"
    assert result.failures[0]["exception_type"] == "RuntimeError"


def test_batch_runner_can_stop_on_first_episode_failure(tmp_path: Path) -> None:
    def runner_factory(**kwargs):
        raise RuntimeError("runner failed")

    with pytest.raises(RuntimeError):
        BatchEpisodeRunner(runner_factory=runner_factory).run(
            BatchEpisodeRequest(
                dataset_config=_dataset_config(),
                output_root=tmp_path / "datasets",
                max_episodes=2,
                continue_on_episode_failure=False,
            )
        )


def test_episode_seed_derivation_is_stable() -> None:
    config = _dataset_config()

    assert derive_episode_id(config.dataset_id, source_index=1, episode_index=7) == (
        "tower_crane_llm_dataset_v1-01-00007"
    )
    assert derive_episode_seed(config, source_index=0, episode_index=0) == derive_episode_seed(
        config,
        source_index=0,
        episode_index=0,
    )
    assert derive_episode_seed(config, source_index=0, episode_index=1) != derive_episode_seed(
        config,
        source_index=0,
        episode_index=0,
    )
