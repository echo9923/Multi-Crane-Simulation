from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional, Sequence

import yaml

from backend.app.schemas.command import ExecutedCommand, ParsedCommand
from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.recorder import (
    EpisodeManifest,
    EpisodeSummary,
    SimFrame,
    SimFrameCrane,
    SimFrameWeather,
)
from backend.app.schemas.scheduler import EpisodeResult, SchedulerConfig
from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import (
    DEFAULT_VISIBILITY_PROFILES,
    WeatherState,
    WeatherVisibilityContext,
)
from backend.app.sim.controller import Controller
from backend.app.sim.physics import initialize_crane_state, step_world
from backend.app.sim.scheduler import EpisodeRunner, SchedulerDependencies


def build_local_episode_runner(
    *,
    episode_id: str,
    resolved_config: Any,
) -> Any:
    """Assemble a deterministic local EpisodeRunner for CLI/single-node use."""
    crane_configs = _crane_configs_from_resolved_config(resolved_config)
    crane_states = [initialize_crane_state(config) for config in crane_configs]
    weather_state, visibility_context = _weather_for_time(resolved_config, 0.0)
    recorder = LocalFileRecorder(
        resolved_config=resolved_config,
        crane_configs=crane_configs,
    )
    dependencies = SchedulerDependencies(
        weather=LocalWeather(resolved_config),
        task_system=NoopTaskSystem(),
        observation_builder=NeutralObservationBuilder(),
        operator=NeutralOperator(),
        safety=PassThroughSafety(),
        controller=Controller.from_config(resolved_config),
        physics=PhysicsAdapter(),
        risk=NoopRisk(),
        collision=NoopCollision(),
        recorder=recorder,
    )
    runner = EpisodeRunner(
        config=_scheduler_config_for_local_run(resolved_config),
        dependencies=dependencies,
        episode_id=episode_id,
        crane_configs=crane_configs,
        crane_states=crane_states,
        weather_state=weather_state,
        visibility_context=visibility_context,
        task_queues=[],
        task_contexts=_idle_task_contexts(crane_configs, 0.0),
    )
    return LocalEpisodeRunner(runner=runner, recorder=recorder)


@dataclass
class LocalEpisodeRunner:
    runner: EpisodeRunner
    recorder: "LocalFileRecorder"

    @property
    def episode_status(self) -> Any:
        return self.runner.episode_status

    def run_one_frame(self) -> Any:
        result = self.runner.run_one_frame()
        if _enum_or_value(result.status) != "running":
            if not self.recorder.frames:
                # Cold stops can become terminal before J emits its first frame.
                self.runner._record_initial_frame()
            self.recorder.finalize(episode_status=result.status)
        return result

    def run_episode(self) -> EpisodeResult:
        result = self.runner.run_episode()
        self.recorder.finalize(episode_status=result.status)
        return result

    def stop(self, reason: str = "stopped_by_user") -> None:
        self.runner.stop(reason)


class LocalWeather:
    def __init__(self, resolved_config: Any) -> None:
        self.resolved_config = resolved_config

    def update(self, time_s: float) -> tuple[WeatherState, WeatherVisibilityContext]:
        return _weather_for_time(self.resolved_config, time_s)


class NoopTaskSystem:
    def activate_due_tasks(
        self,
        *,
        time_s: float,
        states: Sequence[CraneState],
        task_queues: Sequence[Any],
    ) -> SimpleNamespace:
        return SimpleNamespace(
            queues=list(task_queues),
            states=list(states),
            events=[],
            task_contexts=_idle_task_contexts_from_states(states, time_s),
        )

    def update_after_physics(
        self,
        *,
        states: Sequence[CraneState],
        commands: Mapping[str, ExecutedCommand],
        time_s: float,
        task_queues: Sequence[Any],
    ) -> SimpleNamespace:
        return SimpleNamespace(
            queues=list(task_queues),
            states=list(states),
            events=[],
            task_contexts=_idle_task_contexts_from_states(states, time_s),
        )


class NeutralObservationBuilder:
    def build_batch(
        self,
        *,
        snapshot: Any,
        crane_ids: Sequence[str],
        risk_hints: Mapping[str, Any],
    ) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                observation_id=f"OBS_{snapshot.snapshot_id}_{crane_id}",
                source_snapshot_id=snapshot.snapshot_id,
                operator_id=f"LOCAL_{crane_id}",
                crane_id=crane_id,
                time_s=snapshot.time_s,
            )
            for crane_id in crane_ids
        ]


class NeutralOperator:
    def decide(
        self,
        observations: Sequence[Any],
        *,
        llm_decision_interval_s: float,
    ) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                parsed_command=_neutral_parsed_command(
                    crane_id=observation.crane_id,
                    snapshot_id=observation.source_snapshot_id,
                    observation_id=observation.observation_id,
                    operator_id=observation.operator_id,
                    time_s=observation.time_s,
                    command_duration_s=max(0.5, min(3.0, llm_decision_interval_s)),
                ),
                episode_failure_reason=None,
            )
            for observation in observations
        ]


class PassThroughSafety:
    def apply_pipeline(
        self,
        parsed_commands: Sequence[ParsedCommand],
        *,
        snapshot: Any,
    ) -> list[ExecutedCommand]:
        return [
            ExecutedCommand.from_raw(
                command_id=f"EXEC_{command.command_id}",
                raw_command=command,
            )
            for command in parsed_commands
        ]


class PhysicsAdapter:
    def step_world(
        self,
        *,
        crane_configs: Sequence[CraneConfig],
        previous_states: Sequence[CraneState],
        control_targets: Sequence[ControlTarget],
        dt: float,
    ) -> list[CraneState]:
        return step_world(
            crane_configs,
            previous_states,
            control_targets,
            dt=dt,
        )


class NoopRisk:
    def evaluate_predecision(
        self,
        *,
        snapshot: Any,
        commands: Mapping[str, ExecutedCommand],
    ) -> SimpleNamespace:
        return SimpleNamespace(hints={})

    def evaluate_after_physics(
        self,
        *,
        states: Sequence[CraneState],
        commands: Mapping[str, ExecutedCommand],
        time_s: float,
    ) -> SimpleNamespace:
        return SimpleNamespace(events=[])


class NoopCollision:
    def detect(
        self,
        *,
        states: Sequence[CraneState],
        risk: Any,
        time_s: float,
    ) -> list[Any]:
        return []


class LocalFileRecorder:
    def __init__(
        self,
        *,
        resolved_config: Any,
        crane_configs: Sequence[CraneConfig],
    ) -> None:
        self.resolved_config = resolved_config
        self.crane_configs = tuple(copy.deepcopy(list(crane_configs)))
        self.scenario_id = _scenario_id(resolved_config)
        self.run_dir: Optional[Path] = None
        self.episode_id: Optional[str] = None
        self.frames: list[SimFrame] = []
        self._finalized = False

    def record_initial_frame(self, **kwargs: Any) -> SimFrame:
        return self._record_frame(**kwargs)

    def record_step(self, **kwargs: Any) -> SimFrame:
        return self._record_frame(**kwargs)

    def finalize(self, *, episode_status: Any) -> EpisodeSummary:
        if self._finalized and self.episode_id is not None:
            return _read_summary(self._summary_path())
        if self.run_dir is None or self.episode_id is None:
            raise RuntimeError("cannot finalize recorder before any frame is recorded")
        summary = EpisodeSummary(
            episode_id=self.episode_id,
            scenario_id=self.scenario_id,
            episode_status=_enum_or_value(episode_status),
            duration_s=self.frames[-1].time_s if self.frames else 0.0,
            num_cranes=len(self.crane_configs),
            num_tasks_total=0,
            num_tasks_completed=0,
            num_tasks_failed=0,
            task_completion_rate=0.0,
            deadline_missed_count=0,
            overtime_mean_s=0.0,
            risk_frame_ratio_by_level={},
            near_miss_count=0,
            collision_count=0,
            high_risk_duration_s=0.0,
            num_llm_calls=0,
            llm_invalid_output_count=0,
            llm_timeout_count=0,
            cache_hit_count=0,
            operator_profile_distribution={},
            ignored_risk_hint_count=0,
            emergency_stop_count=0,
            forbidden_zone_violation_count=0,
            overlap_zone_shared_count=0,
            has_nan=False,
            has_inf=False,
            replay_available=False,
        )
        manifest = EpisodeManifest(
            episode_id=self.episode_id,
            scenario_id=self.scenario_id,
            episode_status=summary.episode_status,
            frame_count=len(self.frames),
            dt=max(_configured_dt(self.resolved_config), 1.0e-9),
            cranes=[config.model_dump(mode="json") for config in self.crane_configs],
            site=_scenario_mapping(self.resolved_config).get("site", {}),
            material_zones=_scenario_mapping(self.resolved_config)
            .get("site", {})
            .get("material_zones", []),
            work_zones=_scenario_mapping(self.resolved_config)
            .get("site", {})
            .get("work_zones", []),
            forbidden_zones=_scenario_mapping(self.resolved_config)
            .get("site", {})
            .get("forbidden_zones", []),
            overlap_zones=_scenario_mapping(self.resolved_config)
            .get("site", {})
            .get("overlap_zones", []),
            offline_labels_available=False,
        )
        self._write_json(self._summary_path(), summary.model_dump(mode="json"))
        self._write_json(
            self.run_dir / "visual" / "episode_manifest.json",
            manifest.model_dump(mode="json"),
        )
        self._update_metadata(summary.episode_status)
        self._finalized = True
        return summary

    def _record_frame(self, **kwargs: Any) -> SimFrame:
        episode_id = str(kwargs["episode_id"])
        self._ensure_run_dir(episode_id)
        commands = dict(kwargs.get("commands") or {})
        frame = SimFrame(
            episode_id=episode_id,
            scenario_id=self.scenario_id,
            frame=kwargs["frame_index"],
            time_s=kwargs["time_s"],
            episode_status=_enum_or_value(kwargs.get("status", "running")),
            cranes=[
                _frame_crane_from_state(state, commands.get(state.crane_id))
                for state in kwargs["states"]
            ],
            pairs=[],
            tasks=[],
            weather=_frame_weather(kwargs["weather_state"]),
            events=[_dump_jsonable(event) for event in kwargs.get("events", [])],
        )
        self.frames.append(frame)
        assert self.run_dir is not None
        frames_path = self.run_dir / "visual" / "frames.jsonl"
        with frames_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(frame.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
        return frame

    def _ensure_run_dir(self, episode_id: str) -> None:
        if self.run_dir is not None:
            if episode_id != self.episode_id:
                raise RuntimeError("local recorder cannot switch episode_id")
            return
        self.episode_id = episode_id
        self.run_dir = Path(_output_run_root(self.resolved_config)).expanduser().resolve()
        if self.run_dir.name != episode_id:
            self.run_dir = self.run_dir / episode_id
        for dirname in ["config", "metadata", "logs", "data", "replay", "visual"]:
            (self.run_dir / dirname).mkdir(parents=True, exist_ok=True)
        self._write_yaml(
            self.run_dir / "config" / "resolved_config.yaml",
            _dump_jsonable(self.resolved_config),
        )
        self._write_yaml(
            self.run_dir / "config" / "scenario.yaml",
            _scenario_mapping(self.resolved_config),
        )
        self._write_yaml(
            self.run_dir / "config" / "experiment.yaml",
            _experiment_mapping(self.resolved_config),
        )
        dataset = getattr(self.resolved_config, "dataset", None)
        if dataset is not None:
            self._write_yaml(
                self.run_dir / "config" / "dataset.yaml",
                _dump_jsonable(dataset),
            )
        self._write_json(
            self.run_dir / "metadata" / "episode_metadata.json",
            {
                "schema_version": "1.0",
                "episode_id": episode_id,
                "scenario_id": self.scenario_id,
                "episode_status": "running",
                "resolved_config_hash": getattr(
                    self.resolved_config,
                    "resolved_config_hash",
                    None,
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "files": {
                    "frames": "visual/frames.jsonl",
                    "episode_manifest": "visual/episode_manifest.json",
                },
                "warnings": [],
            },
        )

    def _summary_path(self) -> Path:
        if self.run_dir is None:
            raise RuntimeError("run directory not initialized")
        return self.run_dir / "metadata" / "episode_summary.json"

    def _update_metadata(self, episode_status: str) -> None:
        if self.run_dir is None:
            return
        path = self.run_dir / "metadata" / "episode_metadata.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["episode_status"] = episode_status
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        files = dict(payload.get("files", {}))
        files["episode_summary"] = "metadata/episode_summary.json"
        payload["files"] = files
        self._write_json(path, payload)

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _write_yaml(path: Path, payload: object) -> None:
        path.write_text(
            yaml.safe_dump(payload, sort_keys=True, allow_unicode=True),
            encoding="utf-8",
        )


def _scheduler_config_for_local_run(resolved_config: Any) -> SchedulerConfig:
    config = SchedulerConfig.from_config(resolved_config)
    short_duration = max(config.dt_s, min(config.duration_s, config.dt_s * 2))
    return config.model_copy(
        update={
            "duration_s": short_duration,
            "min_duration_s": 0.0,
            "stop_when_all_tasks_done": False,
            "completion_cooldown_s": 0.0,
            "realtime_wall_clock": False,
        }
    )


def _crane_configs_from_resolved_config(resolved_config: Any) -> list[CraneConfig]:
    layout = getattr(resolved_config, "layout", None)
    cranes = getattr(layout, "resolved_cranes", None) if layout is not None else None
    if cranes is None and isinstance(layout, Mapping):
        cranes = layout.get("resolved_cranes")
    if not cranes:
        raise ValueError("resolved config does not include layout.resolved_cranes")
    return [CraneConfig.model_validate(crane) for crane in cranes]


def _weather_for_time(
    resolved_config: Any,
    time_s: float,
) -> tuple[WeatherState, WeatherVisibilityContext]:
    weather = _scenario_mapping(resolved_config).get("weather", {})
    wind = weather.get("wind", {})
    precipitation = weather.get("precipitation", {})
    visibility_level = weather.get("visibility", {}).get("base_level", "good")
    profile = DEFAULT_VISIBILITY_PROFILES[visibility_level]
    weather_state = WeatherState(
        time_s=time_s,
        mode=weather.get("mode", "constant"),
        wind_speed_m_s=wind.get("base_speed_m_s", 0.0),
        wind_gust_m_s=wind.get("gust_speed_m_s", wind.get("base_speed_m_s", 0.0)),
        wind_direction_deg=wind.get("direction_deg", 0.0),
        visibility_level=visibility_level,
        rain_level=precipitation.get("rain_level", "none"),
        fog_level=precipitation.get("fog_level", "none"),
        neighbor_visibility_radius_m=profile.neighbor_visibility_radius_m,
        distance_noise_m=profile.distance_noise_m,
        hide_hook_prob=profile.hide_hook_prob,
        visibility_confidence=profile.visibility_confidence,
        source_segment_id="local-default",
        generation_seed=getattr(getattr(resolved_config, "seeds", None), "weather", 0),
        generation_step=int(round(time_s / max(_configured_dt(resolved_config), 1e-9))),
    )
    visibility_context = WeatherVisibilityContext(
        time_s=time_s,
        visibility_level=visibility_level,
        neighbor_visibility_radius_m=profile.neighbor_visibility_radius_m,
        distance_noise_m=profile.distance_noise_m,
        hide_hook_prob=profile.hide_hook_prob,
        visibility_confidence=profile.visibility_confidence,
        distance_precision_m=profile.distance_precision_m,
        noise_seed=weather_state.generation_seed,
        profile_source="default",
    )
    return weather_state, visibility_context


def _neutral_parsed_command(
    *,
    crane_id: str,
    snapshot_id: str,
    observation_id: str,
    operator_id: str,
    time_s: float,
    command_duration_s: float,
) -> ParsedCommand:
    return ParsedCommand(
        command_id=f"cmd-local-{crane_id}-{time_s:.3f}".replace(".", "p"),
        response_id=f"resp-local-{crane_id}-{time_s:.3f}".replace(".", "p"),
        observation_id=observation_id,
        source_snapshot_id=snapshot_id,
        operator_id=operator_id,
        crane_id=crane_id,
        time_s=time_s,
        left_joystick={
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": "neutral", "gear": 0},
        },
        right_joystick={"hoist": {"direction": "neutral", "gear": 0}},
        deadman_pressed=True,
        emergency_stop=False,
        horn=False,
        command_duration_s=command_duration_s,
        task_action="none",
        attention_target="local_cli_runner",
        confidence=1.0,
        reason="deterministic local neutral command",
    )


def _frame_crane_from_state(
    state: CraneState,
    command: Optional[ExecutedCommand],
) -> SimFrameCrane:
    return SimFrameCrane(
        crane_id=state.crane_id,
        base=(float(state.root_position[0]), float(state.root_position[1]), 0.0),
        root=_xyz_tuple(state.root_position),
        tip=_xyz_tuple(state.tip_position),
        hook=_xyz_tuple(state.hook_position),
        theta_rad=state.theta_rad,
        trolley_r_m=state.trolley_r_m,
        hook_h_m=state.hook_h_m,
        load_attached=state.load_attached,
        load_type=state.load_type,
        load_size_m=_optional_xyz_tuple(state.load_size_m),
        task_id=state.task_id,
        task_stage=state.task_stage,
        current_command=command.model_dump(mode="json") if command is not None else None,
    )


def _frame_weather(weather_state: WeatherState) -> SimFrameWeather:
    return SimFrameWeather(
        wind_speed_m_s=weather_state.wind_speed_m_s,
        wind_gust_m_s=weather_state.wind_gust_m_s,
        wind_direction_deg=weather_state.wind_direction_deg,
        visibility=_enum_or_value(weather_state.visibility_level),
        rain_level=_enum_or_value(weather_state.rain_level),
        fog_level=_enum_or_value(weather_state.fog_level),
    )


def _idle_task_contexts(
    crane_configs: Sequence[CraneConfig],
    time_s: float,
) -> dict[str, dict[str, Any]]:
    return {
        config.crane_id: {
            "crane_id": config.crane_id,
            "time_s": time_s,
            "has_active_task": False,
            "task_stage": "idle",
        }
        for config in crane_configs
    }


def _idle_task_contexts_from_states(
    states: Sequence[CraneState],
    time_s: float,
) -> dict[str, dict[str, Any]]:
    return {
        state.crane_id: {
            "crane_id": state.crane_id,
            "time_s": time_s,
            "has_active_task": False,
            "task_stage": state.task_stage,
        }
        for state in states
    }


def _scenario_mapping(resolved_config: Any) -> dict[str, Any]:
    return dict(getattr(resolved_config, "scenario", {}) or {})


def _experiment_mapping(resolved_config: Any) -> dict[str, Any]:
    return dict(getattr(resolved_config, "experiment", {}) or {})


def _scenario_id(resolved_config: Any) -> Optional[str]:
    value = _scenario_mapping(resolved_config).get("scenario_id")
    return str(value) if value is not None else None


def _output_run_root(resolved_config: Any) -> str:
    output = getattr(resolved_config, "output", None)
    run_root = getattr(output, "run_root", None)
    if run_root is None and isinstance(output, Mapping):
        run_root = output.get("run_root")
    return str(run_root or "runs")


def _configured_dt(resolved_config: Any) -> float:
    try:
        return float(getattr(resolved_config.runtime, "sim", {})["dt"])
    except Exception:
        return 0.05


def _read_summary(path: Path) -> EpisodeSummary:
    return EpisodeSummary.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _dump_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _dump_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _enum_or_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _xyz_tuple(values: Sequence[float]) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))


def _optional_xyz_tuple(
    values: Optional[Sequence[float]],
) -> Optional[tuple[float, float, float]]:
    return _xyz_tuple(values) if values is not None else None


__all__ = ["build_local_episode_runner"]
