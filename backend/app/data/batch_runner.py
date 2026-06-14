from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.app.core.config_loader import load_experiment_config, load_scenario_config
from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.config import DatasetConfig, ExperimentConfig
from backend.app.schemas.dataset import (
    BatchEpisodeRequest,
    BatchEpisodeResult,
    DATASET_SCHEMA_VERSION,
    DatasetBuildWarning,
    assert_no_secret_payload,
)


class BatchEpisodeRunner:
    def __init__(self, *, runner_factory: Callable[..., Any]) -> None:
        self.runner_factory = runner_factory

    def run(self, request: BatchEpisodeRequest) -> BatchEpisodeResult:
        output_dir = request.output_root / request.dataset_config.dataset_id
        metadata_dir = output_dir / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        planned = _planned_episode_specs(request.dataset_config)
        if request.max_episodes is not None:
            planned = planned[: request.max_episodes]

        completed = 0
        failures: list[dict[str, Any]] = []
        run_dirs: list[Path] = []
        report_episodes: list[dict[str, Any]] = []

        for spec in planned:
            try:
                scenario = load_scenario_config(spec["scenario_ref"])
                experiment = _experiment_with_episode_seed(
                    load_experiment_config(spec["experiment_template_ref"]),
                    seed=spec["episode_seed"],
                    run_root=str(output_dir / "episodes"),
                )
                resolved_config = resolve_config(scenario, experiment, request.dataset_config)
                runner = self.runner_factory(
                    episode_id=spec["episode_id"],
                    resolved_config=resolved_config,
                )
                episode_result = runner.run_episode()
                run_dir = _runner_run_dir(runner) or output_dir / "episodes" / spec["episode_id"]
                run_dirs.append(Path(run_dir))
                completed += 1
                report_episodes.append(
                    {
                        **spec,
                        "status": "completed",
                        "runner_status": _status_value(getattr(episode_result, "status", None)),
                        "run_dir": str(run_dir),
                        "final_time_s": getattr(episode_result, "final_time_s", None),
                        "final_frame_index": getattr(
                            episode_result,
                            "final_frame_index",
                            None,
                        ),
                    }
                )
            except Exception as exc:
                failure = {
                    **spec,
                    "status": "failed",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
                failures.append(failure)
                report_episodes.append(failure)
                if not request.continue_on_episode_failure:
                    raise

        report_path = metadata_dir / "generation_report.json"
        report = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "dataset_id": request.dataset_config.dataset_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "seed_derivation": "hash_v1",
            "requested_episodes": len(planned),
            "completed_episodes": completed,
            "failed_episodes": len(failures),
            "episodes": report_episodes,
        }
        assert_no_secret_payload(report, context="generation_report")
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        return BatchEpisodeResult(
            dataset_id=request.dataset_config.dataset_id,
            requested_episodes=len(planned),
            completed_episodes=completed,
            failed_episodes=len(failures),
            run_dirs=run_dirs,
            generation_report_path=report_path,
            failures=failures,
            warnings=_batch_warnings(request.dataset_config, failures),
        )


def derive_episode_id(dataset_id: str, *, source_index: int, episode_index: int) -> str:
    return f"{dataset_id}-{source_index:02d}-{episode_index:05d}"


def derive_episode_seed(
    dataset_config: DatasetConfig,
    *,
    source_index: int,
    episode_index: int,
) -> int:
    source = dataset_config.sources[source_index]
    source_key = "|".join(
        [
            dataset_config.dataset_id,
            str(source.scenario_ref),
            str(source.experiment_template_ref),
        ]
    )
    base = int(hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:8], 16)
    return (base + source_index * 100000 + episode_index) % (2**31 - 1)


def _planned_episode_specs(dataset_config: DatasetConfig) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for source_index, source in enumerate(dataset_config.sources):
        for episode_index in range(source.num_episodes):
            specs.append(
                {
                    "episode_id": derive_episode_id(
                        dataset_config.dataset_id,
                        source_index=source_index,
                        episode_index=episode_index,
                    ),
                    "source_index": source_index,
                    "episode_index": episode_index,
                    "scenario_ref": source.scenario_ref,
                    "experiment_template_ref": source.experiment_template_ref,
                    "episode_seed": derive_episode_seed(
                        dataset_config,
                        source_index=source_index,
                        episode_index=episode_index,
                    ),
                }
            )
    return specs


def _experiment_with_episode_seed(
    experiment: ExperimentConfig,
    *,
    seed: int,
    run_root: str,
) -> ExperimentConfig:
    return experiment.model_copy(
        update={
            "seed": seed,
            "output": experiment.output.model_copy(update={"run_root": run_root}),
        }
    )


def _runner_run_dir(runner: Any) -> Path | None:
    recorder = getattr(runner, "recorder", None)
    run_dir = getattr(recorder, "run_dir", None)
    return Path(run_dir) if run_dir is not None else None


def _status_value(status: Any) -> Any:
    return status.value if hasattr(status, "value") else status


def _batch_warnings(
    dataset_config: DatasetConfig,
    failures: list[dict[str, Any]],
) -> list[DatasetBuildWarning]:
    if not failures:
        return []
    return [
        DatasetBuildWarning(
            warning_code="DATASET_W_EPISODE_FAILURES",
            message="some batch episodes failed",
            details={
                "dataset_id": dataset_config.dataset_id,
                "failed_episodes": len(failures),
            },
        )
    ]


__all__ = [
    "BatchEpisodeRequest",
    "BatchEpisodeResult",
    "BatchEpisodeRunner",
    "derive_episode_id",
    "derive_episode_seed",
]
