from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from backend.app.core.config_loader import load_dataset_config, load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.data.batch_runner import BatchEpisodeRequest, BatchEpisodeRunner
from backend.app.data.catalog import DatasetCatalog
from backend.app.data.dataset_builder import DatasetBuilder
from backend.app.data.quality import DatasetQualityGate
from backend.app.data.splits import DatasetSplitPlanner
from backend.app.data.window_index import DatasetWindowIndexer
from backend.app.schemas.dataset import DatasetBuildOptions

from .episode_service import default_runner_factory

EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_EPISODE_FAILED = 2
EXIT_REPLAY_MISMATCH = 3
EXIT_DATASET_FAILED = 4


@dataclass
class CliResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


def run_episode_from_config(
    config_path: Path,
    *,
    output_json: bool = False,
    overrides: Optional[dict[str, Any]] = None,
    runner_factory: Callable[..., Any] = default_runner_factory,
) -> CliResult:
    try:
        scenario, experiment, dataset = load_demo_config(config_path, overrides=overrides)
        if experiment is None:
            raise ValueError("demo config must include experiment section")
        resolved = resolve_config(scenario, experiment, dataset)
    except Exception as exc:
        return CliResult(
            exit_code=EXIT_INPUT_ERROR,
            stderr=f"{exc}\n",
        )

    try:
        runner = runner_factory(episode_id="cli-episode", resolved_config=resolved)
        episode_result = runner.run_episode()
    except Exception as exc:
        return CliResult(
            exit_code=EXIT_EPISODE_FAILED,
            stderr=f"{exc}\n",
        )

    payload = _episode_result_payload(
        episode_result,
        run_dir=_runner_run_dir(runner) or _resolved_run_dir(resolved),
    )
    if output_json:
        return CliResult(
            exit_code=EXIT_OK,
            stdout=json.dumps(payload, sort_keys=True) + "\n",
        )
    return CliResult(
        exit_code=EXIT_OK,
        stdout=(
            f"episode_id={payload['episode_id']} "
            f"status={payload['status']} "
            f"run_dir={payload['run_dir']}\n"
        ),
    )


def replay_episode_from_run(
    run_dir: Path,
    *,
    output_json: bool = False,
) -> CliResult:
    replay_file = run_dir / "replay" / "command_replay.jsonl"
    if not replay_file.is_file():
        return CliResult(
            exit_code=EXIT_REPLAY_MISMATCH,
            stderr=f"command_replay.jsonl not found under {run_dir}\n",
        )
    return CliResult(
        exit_code=EXIT_REPLAY_MISMATCH,
        stderr="offline replay runner is not implemented\n",
    )


def batch_generate_from_config(
    config_path: Path,
    *,
    max_episodes: Optional[int] = None,
    output_json: bool = False,
    output_root: Optional[Path] = None,
    runner_factory: Callable[..., Any] = default_runner_factory,
) -> CliResult:
    if max_episodes is not None and max_episodes <= 0:
        return CliResult(
            exit_code=EXIT_INPUT_ERROR,
            stderr="--max-episodes must be positive\n",
        )
    try:
        dataset = load_dataset_config(config_path)
    except Exception as exc:
        return CliResult(
            exit_code=EXIT_INPUT_ERROR,
            stderr=f"{exc}\n",
        )
    try:
        result = BatchEpisodeRunner(runner_factory=runner_factory).run(
            BatchEpisodeRequest(
                dataset_config=dataset,
                output_root=output_root or Path(dataset.run_root) / "datasets",
                max_episodes=max_episodes,
            )
        )
    except Exception as exc:
        return CliResult(
            exit_code=EXIT_DATASET_FAILED,
            stderr=f"{exc}\n",
        )
    payload = result.model_dump(mode="json")
    if output_json:
        return CliResult(
            exit_code=EXIT_OK,
            stdout=json.dumps(payload, sort_keys=True) + "\n",
        )
    return CliResult(
        exit_code=EXIT_OK,
        stdout=(
            f"dataset_id={payload['dataset_id']} "
            f"completed={payload['completed_episodes']} "
            f"failed={payload['failed_episodes']} "
            f"generation_report={payload['generation_report_path']}\n"
        ),
    )


def build_dataset_from_config(
    config_path: Path,
    *,
    source_roots: list[Path],
    output_root: Path,
    copy_mode: str = "index_only",
    max_episodes: Optional[int] = None,
    output_json: bool = False,
) -> CliResult:
    if max_episodes is not None and max_episodes <= 0:
        return CliResult(
            exit_code=EXIT_INPUT_ERROR,
            stderr="--max-episodes must be positive\n",
        )
    try:
        dataset = load_dataset_config(config_path)
        result = DatasetBuilder(
            catalog=DatasetCatalog(),
            quality_gate=DatasetQualityGate(),
            split_planner=DatasetSplitPlanner(config=dataset),
            window_indexer=DatasetWindowIndexer(config=dataset),
        ).build(
            config=dataset,
            options=DatasetBuildOptions(
                source_roots=source_roots,
                output_root=output_root,
                copy_mode=copy_mode,  # type: ignore[arg-type]
                max_episodes=max_episodes,
            ),
        )
    except FileNotFoundError as exc:
        return CliResult(exit_code=EXIT_INPUT_ERROR, stderr=f"{exc}\n")
    except Exception as exc:
        return CliResult(exit_code=EXIT_DATASET_FAILED, stderr=f"{exc}\n")

    payload = result.model_dump(mode="json")
    if output_json:
        return CliResult(
            exit_code=EXIT_OK,
            stdout=json.dumps(payload, sort_keys=True) + "\n",
        )
    return CliResult(
        exit_code=EXIT_OK,
        stdout=(
            f"dataset_id={payload['dataset_id']} "
            f"num_episodes={payload['num_episodes']} "
            f"num_quarantined={payload['num_quarantined']} "
            f"summary={payload['summary_path']}\n"
        ),
    )


def main_run_episode(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one simulation episode.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-json", action="store_true")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        help="Override a demo config field, for example experiment.output.run_root=runs/tmp.",
    )
    args = parser.parse_args(argv)
    result = run_episode_from_config(
        Path(args.config),
        output_json=args.output_json,
        overrides=_parse_demo_overrides(args.override),
    )
    _emit(result)
    return result.exit_code


def main_replay_episode(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay one recorded simulation episode.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--output-json", action="store_true")
    args = parser.parse_args(argv)
    result = replay_episode_from_run(
        Path(args.run),
        output_json=args.output_json,
    )
    _emit(result)
    return result.exit_code


def main_batch_generate(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a batch dataset.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--output-json", action="store_true")
    args = parser.parse_args(argv)
    result = batch_generate_from_config(
        Path(args.config),
        max_episodes=args.max_episodes,
        output_json=args.output_json,
        output_root=Path(args.output_root) if args.output_root else None,
    )
    _emit(result)
    return result.exit_code


def main_build_dataset(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build a dataset from episode runs.")
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--source-root",
        action="append",
        required=True,
        help="Episode source root. Can be passed multiple times.",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--copy-mode",
        default="index_only",
        choices=["copy", "symlink", "hardlink", "index_only"],
    )
    parser.add_argument("--max-episodes", type=int, default=None)
    parser.add_argument("--output-json", action="store_true")
    args = parser.parse_args(argv)
    result = build_dataset_from_config(
        Path(args.config),
        source_roots=[Path(value) for value in args.source_root],
        output_root=Path(args.output_root),
        copy_mode=args.copy_mode,
        max_episodes=args.max_episodes,
        output_json=args.output_json,
    )
    _emit(result)
    return result.exit_code


def _emit(result: CliResult) -> None:
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        import sys

        print(result.stderr, end="", file=sys.stderr)


def _episode_result_payload(episode_result: Any, *, run_dir: Optional[str]) -> dict[str, Any]:
    status = getattr(episode_result, "status", None)
    if hasattr(status, "value"):
        status = status.value
    return {
        "episode_id": getattr(episode_result, "episode_id", None),
        "status": status,
        "run_dir": run_dir,
        "final_time_s": getattr(episode_result, "final_time_s", None),
        "final_frame_index": getattr(episode_result, "final_frame_index", None),
        "summary_path": str(Path(run_dir) / "metadata" / "episode_summary.json")
        if run_dir
        else None,
    }


def _resolved_run_dir(resolved_config: Any) -> Optional[str]:
    output = getattr(resolved_config, "output", None)
    if output is None:
        return None
    run_root = getattr(output, "run_root", None)
    return str(run_root) if run_root else None


def _runner_run_dir(runner: Any) -> Optional[str]:
    recorder = getattr(runner, "recorder", None)
    run_dir = getattr(recorder, "run_dir", None)
    return str(run_dir) if run_dir is not None else None


def _parse_demo_overrides(values: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid --override value: {value}")
        key, raw = value.split("=", 1)
        section, _, field_path = key.partition(".")
        if section not in {"scenario", "experiment", "dataset"} or not field_path:
            raise SystemExit(f"invalid --override path: {key}")
        overrides.setdefault(section, {})[field_path] = _parse_override_value(raw)
    return overrides


def _parse_override_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


__all__ = [
    "CliResult",
    "batch_generate_from_config",
    "build_dataset_from_config",
    "main_batch_generate",
    "main_build_dataset",
    "main_replay_episode",
    "main_run_episode",
    "replay_episode_from_run",
    "run_episode_from_config",
]
