from __future__ import annotations

import math
import random
from typing import Optional

from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.observation import (
    AxisCommand,
    JoystickCommandSummary,
    LeftJoystickCommand,
    OnlineRiskHint,
    RightJoystickCommand,
    SafetyHint,
    SelfStateSummary,
    TaskObservationSummary,
    VisibleNeighbor,
)
from backend.app.schemas.enums import RiskPromptMode
from backend.app.schemas.state import CraneState
from backend.app.schemas.task import TaskPoint
from backend.app.schemas.weather import WeatherVisibilityContext
from backend.app.sim.layout_geometry import horizontal_distance
from backend.app.sim.task_observation import TaskObservationContext
from backend.app.sim.task_queue import IdleObservationContext
from backend.app.sim.weather import build_visibility_sampling_key


class ObservationBuildError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "OBSERVATION_E_INVALID_STATE",
        crane_id: Optional[str] = None,
        field_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = "episode_failed"
        self.episode_status = "failed_invalid_state"
        self.crane_id = crane_id
        self.field_path = field_path


def build_self_state_summary(
    *,
    state: CraneState,
    crane_config: CraneConfig,
    current_command: Optional[ControlTarget],
    distance_precision_m: float,
) -> SelfStateSummary:
    if state.crane_id != crane_config.crane_id:
        raise ObservationBuildError(
            "state crane_id must match crane_config crane_id",
            crane_id=state.crane_id,
            field_path="crane_id",
        )
    if current_command is not None and current_command.crane_id != state.crane_id:
        raise ObservationBuildError(
            "current_command crane_id must match state crane_id",
            crane_id=state.crane_id,
            field_path="current_command.crane_id",
        )

    return SelfStateSummary(
        slew_angle_deg=round(math.degrees(state.theta_rad), 1),
        slew_motion=_slew_motion(state.theta_dot_rad_s),
        trolley_r_m=_round_to_precision(state.trolley_r_m, distance_precision_m),
        hook_h_m=_round_to_precision(state.hook_h_m, distance_precision_m),
        load_attached=state.load_attached,
        load_type=state.load_type,
        load_weight_t=_round_to_precision(state.load_weight_t, 0.1),
        current_command=_command_summary(current_command),
    )


def build_task_summary(
    *,
    task_context: TaskObservationContext | IdleObservationContext,
    observer_state: CraneState,
    distance_precision_m: float,
) -> TaskObservationSummary:
    if task_context.crane_id != observer_state.crane_id:
        raise ObservationBuildError(
            "task_context crane_id must match observer_state crane_id",
            crane_id=observer_state.crane_id,
            field_path="task_context.crane_id",
        )

    pickup = _relative_point_summary(
        observer_state=observer_state,
        point=getattr(task_context, "pickup", None),
        distance_precision_m=distance_precision_m,
    )
    dropoff = _relative_point_summary(
        observer_state=observer_state,
        point=getattr(task_context, "dropoff", None),
        distance_precision_m=distance_precision_m,
    )
    current_target = _relative_point_summary(
        observer_state=observer_state,
        point=task_context.current_target,
        distance_precision_m=distance_precision_m,
    )

    return TaskObservationSummary(
        stage=task_context.task_stage,
        has_active_task=task_context.has_active_task,
        type=getattr(task_context, "task_type", None),
        priority=getattr(task_context, "priority", None),
        deadline_s=_optional_round(getattr(task_context, "deadline_s", None), 0.1),
        deadline_missed=getattr(task_context, "deadline_missed", False),
        overtime_s=_round_to_precision(getattr(task_context, "overtime_s", 0.0), 0.1),
        pickup_relative_direction=pickup.relative_direction,
        pickup_distance_m=pickup.distance_m,
        pickup_height_delta_m=pickup.height_delta_m,
        dropoff_relative_direction=dropoff.relative_direction,
        dropoff_distance_m=dropoff.distance_m,
        dropoff_height_delta_m=dropoff.height_delta_m,
        current_target_relative_direction=current_target.relative_direction,
        current_target_distance_m=current_target.distance_m,
        current_target_height_delta_m=current_target.height_delta_m,
        load_attached=getattr(task_context, "load_attached", False),
        load_type=getattr(task_context, "load_type", None),
        load_weight_t=getattr(task_context, "load_weight_t", None),
        signal_hint=task_context.ground_signal_hint,
    )


def build_visible_neighbors(
    *,
    observer_state: CraneState,
    states_by_id: dict[str, CraneState],
    neighbor_ids: list[str],
    visibility: WeatherVisibilityContext,
    decision_time_bucket: int,
) -> list[VisibleNeighbor]:
    neighbors: list[VisibleNeighbor] = []
    for neighbor_id in neighbor_ids:
        try:
            neighbor_state = states_by_id[neighbor_id]
        except KeyError as exc:
            raise ObservationBuildError(
                "neighbor state is missing",
                crane_id=observer_state.crane_id,
                field_path=f"states_by_id.{neighbor_id}",
            ) from exc

        true_distance = horizontal_distance(
            observer_state.hook_position,
            neighbor_state.hook_position,
        )
        if true_distance > visibility.neighbor_visibility_radius_m:
            continue

        observed_distance = _observed_neighbor_distance(
            true_distance=true_distance,
            observer_crane_id=observer_state.crane_id,
            target_crane_id=neighbor_id,
            visibility=visibility,
            decision_time_bucket=decision_time_bucket,
        )
        hook_visible = not _sample_hook_hidden(
            observer_crane_id=observer_state.crane_id,
            target_crane_id=neighbor_id,
            visibility=visibility,
            decision_time_bucket=decision_time_bucket,
        )
        dx = neighbor_state.hook_position[0] - observer_state.hook_position[0]
        dy = neighbor_state.hook_position[1] - observer_state.hook_position[1]
        neighbors.append(
            VisibleNeighbor(
                crane_id=neighbor_id,
                relative_direction=_relative_direction(dx, dy),
                distance_m=observed_distance,
                distance_level=_distance_level(observed_distance),
                hook_visible=hook_visible,
                hook_height_m=(
                    _round_to_precision(
                        neighbor_state.hook_position[2],
                        visibility.distance_precision_m,
                    )
                    if hook_visible
                    else None
                ),
                jib_motion=_slew_motion(neighbor_state.theta_dot_rad_s),
                trolley_motion=_linear_motion(
                    neighbor_state.trolley_v_m_s,
                    positive="out",
                    negative="in",
                ),
                hoist_motion=_linear_motion(
                    neighbor_state.hoist_v_m_s,
                    positive="up",
                    negative="down",
                ),
                load_attached=neighbor_state.load_attached if hook_visible else None,
                task_stage=neighbor_state.task_stage,
                in_overlap_zone=true_distance <= visibility.neighbor_visibility_radius_m,
            )
        )
    return neighbors


def build_safety_hint(
    *,
    risk_prompt_mode: RiskPromptMode,
    online_risk: Optional[OnlineRiskHint],
    visibility: WeatherVisibilityContext,
    distance_precision_m: float,
) -> Optional[SafetyHint]:
    mode = RiskPromptMode(risk_prompt_mode)
    if mode is RiskPromptMode.R0 or online_risk is None:
        return None

    return SafetyHint(
        source=online_risk.source,
        risk_level=online_risk.risk_level,
        nearest_neighbor=online_risk.nearest_neighbor,
        nearest_object_type=online_risk.nearest_object_type,
        clearance_now_m=_optional_round(
            online_risk.clearance_now_m,
            distance_precision_m,
        ),
        estimated_clearance_next_5s_m=_optional_round(
            online_risk.estimated_clearance_next_5s_m,
            distance_precision_m,
        ),
        relative_motion=online_risk.relative_motion,
        confidence=min(online_risk.confidence, visibility.visibility_confidence),
        suggestion=online_risk.suggestion,
    )


def _command_summary(current_command: Optional[ControlTarget]) -> JoystickCommandSummary:
    if current_command is None:
        return JoystickCommandSummary(
            left_joystick=LeftJoystickCommand(
                slew=AxisCommand(direction="neutral", gear=0),
                trolley=AxisCommand(direction="neutral", gear=0),
            ),
            right_joystick=RightJoystickCommand(
                hoist=AxisCommand(direction="neutral", gear=0)
            ),
            deadman_pressed=True,
            emergency_stop=False,
            hold_position=False,
        )

    return JoystickCommandSummary(
        left_joystick=LeftJoystickCommand(
            slew=AxisCommand(
                direction=_axis_direction(
                    current_command.target_slew_velocity_rad_s,
                    positive="left",
                    negative="right",
                ),
                gear=_gear_for_velocity(current_command.target_slew_velocity_rad_s),
            ),
            trolley=AxisCommand(
                direction=_axis_direction(
                    current_command.target_trolley_velocity_m_s,
                    positive="out",
                    negative="in",
                ),
                gear=_gear_for_velocity(current_command.target_trolley_velocity_m_s),
            ),
        ),
        right_joystick=RightJoystickCommand(
            hoist=AxisCommand(
                direction=_axis_direction(
                    current_command.target_hoist_velocity_m_s,
                    positive="up",
                    negative="down",
                ),
                gear=_gear_for_velocity(current_command.target_hoist_velocity_m_s),
            )
        ),
        deadman_pressed=not current_command.emergency_stop,
        emergency_stop=current_command.emergency_stop,
        hold_position=current_command.hold_position,
    )


def _slew_motion(velocity_rad_s: float) -> str:
    direction = _axis_direction(velocity_rad_s, positive="slow_left", negative="slow_right")
    return "hold" if direction == "neutral" else direction


def _linear_motion(value: float, *, positive: str, negative: str) -> str:
    direction = _axis_direction(value, positive=positive, negative=negative)
    return "hold" if direction == "neutral" else direction


def _axis_direction(value: float, *, positive: str, negative: str) -> str:
    if abs(value) < 1e-9:
        return "neutral"
    return positive if value > 0 else negative


def _gear_for_velocity(value: float) -> int:
    if abs(value) < 1e-9:
        return 0
    return 1


def _round_to_precision(value: float, precision: float) -> float:
    if precision <= 0 or not math.isfinite(precision):
        raise ObservationBuildError(
            "distance_precision_m must be finite and positive",
            field_path="distance_precision_m",
        )
    if not math.isfinite(value):
        raise ObservationBuildError("observation value must be finite")
    return round(value / precision) * precision


def _optional_round(value: Optional[float], precision: float) -> Optional[float]:
    if value is None:
        return None
    return _round_to_precision(value, precision)


class _RelativePointSummary:
    def __init__(
        self,
        *,
        relative_direction: Optional[str],
        distance_m: Optional[float],
        height_delta_m: Optional[float],
    ) -> None:
        self.relative_direction = relative_direction
        self.distance_m = distance_m
        self.height_delta_m = height_delta_m


def _relative_point_summary(
    *,
    observer_state: CraneState,
    point: Optional[TaskPoint],
    distance_precision_m: float,
) -> _RelativePointSummary:
    if point is None:
        return _RelativePointSummary(
            relative_direction=None,
            distance_m=None,
            height_delta_m=None,
        )

    hook = observer_state.hook_position
    target = point.as_xyz()
    dx = target[0] - hook[0]
    dy = target[1] - hook[1]
    dz = target[2] - hook[2]
    return _RelativePointSummary(
        relative_direction=_relative_direction(dx, dy),
        distance_m=_round_to_precision(
            horizontal_distance(hook, target),
            distance_precision_m,
        ),
        height_delta_m=_round_to_precision(dz, distance_precision_m),
    )


def _relative_direction(dx: float, dy: float) -> str:
    horizontal = "center"
    if dx > 1e-9:
        horizontal = "right"
    elif dx < -1e-9:
        horizontal = "left"

    vertical = "center"
    if dy > 1e-9:
        vertical = "front"
    elif dy < -1e-9:
        vertical = "back"

    if horizontal == "center" and vertical == "center":
        return "aligned"
    if horizontal == "center":
        return vertical
    if vertical == "center":
        return horizontal
    return f"{horizontal}_{vertical}"


def _observed_neighbor_distance(
    *,
    true_distance: float,
    observer_crane_id: str,
    target_crane_id: str,
    visibility: WeatherVisibilityContext,
    decision_time_bucket: int,
) -> float:
    if visibility.distance_noise_m == 0:
        noisy = true_distance
    else:
        key = build_visibility_sampling_key(
            noise_seed=visibility.noise_seed,
            observer_crane_id=observer_crane_id,
            target_crane_id=target_crane_id,
            decision_time_bucket=decision_time_bucket,
            purpose="distance_noise",
        )
        noisy = true_distance + random.Random(key).uniform(
            -visibility.distance_noise_m,
            visibility.distance_noise_m,
        )
    return max(0.0, _round_to_precision(noisy, visibility.distance_precision_m))


def _sample_hook_hidden(
    *,
    observer_crane_id: str,
    target_crane_id: str,
    visibility: WeatherVisibilityContext,
    decision_time_bucket: int,
) -> bool:
    if visibility.hide_hook_prob <= 0:
        return False
    if visibility.hide_hook_prob >= 1:
        return True
    key = build_visibility_sampling_key(
        noise_seed=visibility.noise_seed,
        observer_crane_id=observer_crane_id,
        target_crane_id=target_crane_id,
        decision_time_bucket=decision_time_bucket,
        purpose="hook_visibility",
    )
    return random.Random(key).random() < visibility.hide_hook_prob


def _distance_level(distance_m: float) -> str:
    if distance_m <= 30.0:
        return "near"
    if distance_m <= 80.0:
        return "medium"
    return "far"
