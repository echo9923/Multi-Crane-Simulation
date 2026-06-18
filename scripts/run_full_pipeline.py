from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.api.cli import RunnerName, _parse_demo_overrides
from backend.app.api.episode_service import default_runner_factory, local_runner_factory
from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.data.catalog import DatasetCatalog
from backend.app.data.dataset_builder import DatasetBuilder
from backend.app.data.quality import DatasetQualityGate
from backend.app.data.splits import DatasetSplitPlanner
from backend.app.data.window_index import DatasetWindowIndexer
from backend.app.schemas.dataset import DatasetBuildOptions
from backend.app.training.converter import StgnnDatasetConverter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the complete A-P smoke pipeline.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--runner",
        choices=["production", "local"],
        default="production",
    )
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="Override a demo config field, for example experiment.sim.duration_s=8.",
    )
    parser.add_argument("--output-json", action="store_true")
    args = parser.parse_args(argv)

    if args.episodes <= 0:
        print("--episodes must be positive", file=sys.stderr)
        return 1

    try:
        payload = run_full_pipeline(
            config_path=Path(args.config),
            episodes=args.episodes,
            output_root=Path(args.output_root),
            runner=args.runner,
            overrides=_parse_demo_overrides(args.override),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.output_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"episodes={len(payload['run_dirs'])} "
            f"dataset_dir={payload['dataset_dir']} "
            f"stgnn_output_root={payload['stgnn_output_root']}"
        )
    return 0


def run_full_pipeline(
    *,
    config_path: Path,
    episodes: int,
    output_root: Path,
    runner: RunnerName = "production",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario, experiment, dataset = load_demo_config(config_path, overrides=overrides)
    if experiment is None:
        raise ValueError("demo config must include experiment section")
    if dataset is None:
        raise ValueError("demo config must include dataset section")

    output_root = output_root.expanduser().resolve()
    episode_root = output_root / "episodes"
    dataset_output_root = output_root / "datasets"
    stgnn_output_root = output_root / "stgnn"
    factory = local_runner_factory if runner == "local" else default_runner_factory

    run_dirs: list[Path] = []
    for index in range(episodes):
        episode_id = f"full-pipeline-{index:04d}"
        episode_experiment = experiment.model_copy(
            update={
                "seed": experiment.seed + index,
                "output": experiment.output.model_copy(
                    update={"run_root": str(episode_root)}
                ),
            }
        )
        resolved = resolve_config(scenario, episode_experiment, dataset)
        runner_instance = factory(
            episode_id=episode_id,
            resolved_config=resolved,
        )
        runner_instance.run_episode()
        run_dir = _runner_run_dir(runner_instance) or episode_root / episode_id
        run_dirs.append(Path(run_dir))

    builder = DatasetBuilder(
        catalog=DatasetCatalog(),
        quality_gate=DatasetQualityGate(
            min_duration_s=0.0,
            required_offline_labels=False,
            require_replay=False,
        ),
        split_planner=DatasetSplitPlanner(config=dataset),
        window_indexer=DatasetWindowIndexer(config=dataset),
    )
    dataset_result = builder.build(
        config=dataset,
        options=DatasetBuildOptions(
            source_roots=[episode_root],
            output_root=dataset_output_root,
            copy_mode="index_only",
            min_duration_s=0.0,
            max_episodes=episodes,
        ),
    )
    stgnn_result = StgnnDatasetConverter(strict=False).convert(
        dataset_root=dataset_result.dataset_dir,
        output_root=stgnn_output_root,
    )
    first_run_dir = run_dirs[0]
    return {
        "run_dirs": [_path_to_json(path) for path in run_dirs],
        "dataset_dir": _path_to_json(dataset_result.dataset_dir),
        "stgnn_output_root": _path_to_json(stgnn_output_root),
        "stgnn_sample_count": len(stgnn_result.samples),
        "frontend_replay_files": {
            "frames_jsonl": _path_to_json(first_run_dir / "visual" / "frames.jsonl"),
            "episode_manifest": _path_to_json(first_run_dir / "visual" / "episode_manifest.json"),
        },
    }


def _path_to_json(path: Path) -> str:
    return path.as_posix()


def _runner_run_dir(runner: Any) -> Path | None:
    recorder = getattr(runner, "recorder", None)
    run_dir = getattr(recorder, "run_dir", None)
    return Path(run_dir) if run_dir is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
