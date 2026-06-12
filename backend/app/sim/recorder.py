from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Mapping, Optional

import yaml

from backend.app.schemas.recorder import RECORDER_SCHEMA_VERSION
from backend.app.schemas.resolved_config import ResolvedConfig


class DataExportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        category: Literal["data_export_error"] = "data_export_error",
        episode_id: Optional[str] = None,
        frame: Optional[int] = None,
        file_path: Optional[str] = None,
        field_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = category
        self.episode_id = episode_id
        self.frame = frame
        self.file_path = file_path
        self.field_path = field_path
        self.details = details or {}


@dataclass(frozen=True)
class RunDirectoryLayout:
    run_root: Path
    config_dir: Path
    metadata_dir: Path
    logs_dir: Path
    data_dir: Path
    replay_dir: Path
    visual_dir: Path
    resolved_config_path: Path
    scenario_config_path: Path
    experiment_config_path: Path
    dataset_config_path: Path
    episode_metadata_path: Path
    episode_summary_path: Path
    dataset_summary_path: Path
    episode_manifest_path: Path
    frames_jsonl_path: Path
    trajectories_path: Path
    pair_risks_path: Path
    graph_edges_path: Path
    tasks_path: Path
    weather_path: Path
    observations_path: Path
    decisions_path: Path
    commands_path: Path
    interventions_path: Path
    events_path: Path


def init_run_directory(
    *,
    config: object,
    episode_id: str,
    scenario_id: Optional[str] = None,
    run_root_override: Optional[Path] = None,
) -> RunDirectoryLayout:
    resolved_config = _coerce_resolved_config(config)
    layout = _build_layout(
        resolved_config=resolved_config,
        episode_id=episode_id,
        run_root_override=run_root_override,
    )
    try:
        for directory in [
            layout.config_dir,
            layout.metadata_dir,
            layout.logs_dir,
            layout.data_dir,
            layout.replay_dir,
            layout.visual_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
        _write_config_files(layout, resolved_config)
        _write_episode_metadata(
            layout,
            resolved_config=resolved_config,
            episode_id=episode_id,
            scenario_id=scenario_id or _scenario_id_from_config(resolved_config),
        )
    except OSError as exc:
        raise DataExportError(
            "failed to initialize recorder run directory",
            error_code="RECORDER_E_RUN_DIRECTORY",
            episode_id=episode_id,
            file_path=str(layout.run_root),
            details={"exception_type": type(exc).__name__, "reason": str(exc)},
        ) from exc
    return layout


def _coerce_resolved_config(config: object) -> ResolvedConfig:
    if isinstance(config, ResolvedConfig):
        return config
    if isinstance(config, Mapping):
        return ResolvedConfig.model_validate(config)
    if hasattr(config, "model_dump"):
        return ResolvedConfig.model_validate(config.model_dump(mode="json"))
    raise DataExportError(
        "recorder requires a ResolvedConfig-compatible object",
        error_code="RECORDER_E_INVALID_CONFIG",
        field_path="config",
    )


def _build_layout(
    *,
    resolved_config: ResolvedConfig,
    episode_id: str,
    run_root_override: Optional[Path],
) -> RunDirectoryLayout:
    root = Path(
        run_root_override or resolved_config.output.run_root
    ).expanduser().resolve()
    run_root = root / episode_id
    config_dir = run_root / "config"
    metadata_dir = run_root / "metadata"
    logs_dir = run_root / "logs"
    data_dir = run_root / "data"
    replay_dir = run_root / "replay"
    visual_dir = run_root / "visual"
    return RunDirectoryLayout(
        run_root=run_root,
        config_dir=config_dir,
        metadata_dir=metadata_dir,
        logs_dir=logs_dir,
        data_dir=data_dir,
        replay_dir=replay_dir,
        visual_dir=visual_dir,
        resolved_config_path=config_dir / "resolved_config.yaml",
        scenario_config_path=config_dir / "scenario.yaml",
        experiment_config_path=config_dir / "experiment.yaml",
        dataset_config_path=config_dir / "dataset.yaml",
        episode_metadata_path=metadata_dir / "episode_metadata.json",
        episode_summary_path=metadata_dir / "episode_summary.json",
        dataset_summary_path=metadata_dir / "dataset_summary.json",
        episode_manifest_path=visual_dir / "episode_manifest.json",
        frames_jsonl_path=visual_dir / "frames.jsonl",
        trajectories_path=data_dir / "trajectories.parquet",
        pair_risks_path=data_dir / "pair_risks.parquet",
        graph_edges_path=data_dir / "graph_edges.parquet",
        tasks_path=data_dir / "tasks.parquet",
        weather_path=data_dir / "weather.parquet",
        observations_path=logs_dir / "llm_observations.jsonl",
        decisions_path=logs_dir / "llm_decisions.jsonl",
        commands_path=logs_dir / "commands.jsonl",
        interventions_path=logs_dir / "interventions.jsonl",
        events_path=logs_dir / "events.jsonl",
    )


def _write_config_files(
    layout: RunDirectoryLayout,
    resolved_config: ResolvedConfig,
) -> None:
    payload = resolved_config.model_dump(mode="json")
    _write_yaml(layout.resolved_config_path, payload)
    _write_yaml(layout.scenario_config_path, resolved_config.scenario)
    _write_yaml(layout.experiment_config_path, resolved_config.experiment)
    if resolved_config.dataset is not None:
        _write_yaml(layout.dataset_config_path, resolved_config.dataset)


def _write_yaml(path: Path, payload: object) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )


def _write_episode_metadata(
    layout: RunDirectoryLayout,
    *,
    resolved_config: ResolvedConfig,
    episode_id: str,
    scenario_id: Optional[str],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing_created_at = now
    if layout.episode_metadata_path.exists():
        try:
            existing = json.loads(
                layout.episode_metadata_path.read_text(encoding="utf-8")
            )
            existing_created_at = existing.get("created_at", now)
        except (OSError, json.JSONDecodeError):
            existing_created_at = now
    metadata = {
        "schema_version": RECORDER_SCHEMA_VERSION,
        "episode_id": episode_id,
        "scenario_id": scenario_id,
        "episode_status": "running",
        "resolved_config_hash": resolved_config.resolved_config_hash,
        "created_at": existing_created_at,
        "updated_at": now,
        "files": {
            "trajectories": "data/trajectories.parquet",
            "pair_risks": "data/pair_risks.parquet",
            "graph_edges": "data/graph_edges.parquet",
            "tasks": "data/tasks.parquet",
            "weather": "data/weather.parquet",
            "frames": "visual/frames.jsonl",
            "episode_manifest": "visual/episode_manifest.json",
            "commands": "logs/commands.jsonl",
            "events": "logs/events.jsonl",
            "llm_observations": "logs/llm_observations.jsonl",
            "llm_decisions": "logs/llm_decisions.jsonl",
            "interventions": "logs/interventions.jsonl",
        },
        "warnings": [],
    }
    layout.episode_metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _scenario_id_from_config(resolved_config: ResolvedConfig) -> Optional[str]:
    scenario = resolved_config.scenario
    value = scenario.get("scenario_id") if isinstance(scenario, dict) else None
    return str(value) if value is not None else None
