from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, TypeVar

from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.state import CraneState

T = TypeVar("T")


class PhysicsWorldError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason: str,
        crane_id: Optional[str] = None,
        field_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.crane_id = crane_id
        self.field_path = field_path


def initialize_crane_state(crane_config: CraneConfig) -> CraneState:
    theta_rad = crane_config.theta_init_rad
    hook_h_m = crane_config.hook_h_max_world_m
    trolley_r_m = crane_config.trolley_r_min_m
    state = CraneState(
        crane_id=crane_config.crane_id,
        theta_rad=theta_rad,
        theta_dot_rad_s=0.0,
        theta_ddot_rad_s2=0.0,
        theta_sin=math.sin(theta_rad),
        theta_cos=math.cos(theta_rad),
        trolley_r_m=trolley_r_m,
        trolley_v_m_s=0.0,
        hook_h_m=hook_h_m,
        hoist_v_m_s=0.0,
        root_position=[float(value) for value in crane_config.root],
        tip_position=compute_tip_position(crane_config, theta_rad),
        hook_position=compute_hook_position(
            crane_config,
            theta_rad,
            trolley_r_m=trolley_r_m,
            hook_h_m=hook_h_m,
        ),
        cable_length_m=crane_config.root[2] - hook_h_m,
        load_position=None,
        swing_angle_rad=0.0,
        swing_velocity_rad_s=0.0,
        wind_effect_on_swing=None,
        load_attached=False,
        load_type=None,
        load_weight_t=0.0,
        load_size_m=None,
        task_id=None,
        task_stage="idle",
    )
    return recompute_state_geometry(crane_config, state)


def initialize_world_state(crane_configs: Sequence[CraneConfig]) -> list[CraneState]:
    return [initialize_crane_state(crane_config) for crane_config in crane_configs]


def compute_tip_position(crane_config: CraneConfig, theta_rad: float) -> list[float]:
    return [
        crane_config.root[0] + crane_config.jib_length_m * math.cos(theta_rad),
        crane_config.root[1] + crane_config.jib_length_m * math.sin(theta_rad),
        crane_config.root[2],
    ]


def compute_hook_position(
    crane_config: CraneConfig,
    theta_rad: float,
    *,
    trolley_r_m: float,
    hook_h_m: float,
) -> list[float]:
    return [
        crane_config.base[0] + trolley_r_m * math.cos(theta_rad),
        crane_config.base[1] + trolley_r_m * math.sin(theta_rad),
        hook_h_m,
    ]


def recompute_state_geometry(
    crane_config: CraneConfig,
    state: CraneState,
) -> CraneState:
    theta_sin = math.sin(state.theta_rad)
    theta_cos = math.cos(state.theta_rad)
    hook_position = compute_hook_position(
        crane_config,
        state.theta_rad,
        trolley_r_m=state.trolley_r_m,
        hook_h_m=state.hook_h_m,
    )
    load_position = hook_position if state.load_attached else None
    return state.model_copy(
        update={
            "theta_sin": theta_sin,
            "theta_cos": theta_cos,
            "root_position": [float(value) for value in crane_config.root],
            "tip_position": compute_tip_position(crane_config, state.theta_rad),
            "hook_position": hook_position,
            "cable_length_m": crane_config.root[2] - state.hook_h_m,
            "load_position": load_position,
        }
    )


def step_crane_state(
    crane_config: CraneConfig,
    previous_state: CraneState,
    control_target: ControlTarget,
    dt: float,
) -> CraneState:
    target_slew = control_target.target_slew_velocity_rad_s
    target_trolley = control_target.target_trolley_velocity_m_s
    target_hoist = control_target.target_hoist_velocity_m_s
    if control_target.emergency_stop or control_target.hold_position:
        target_slew = 0.0
        target_trolley = 0.0
        target_hoist = 0.0

    theta_dot = _approach(
        previous_state.theta_dot_rad_s,
        _clip(
            target_slew,
            -crane_config.model.slew_speed_max_rad_s,
            crane_config.model.slew_speed_max_rad_s,
        ),
        crane_config.model.slew_acc_max_rad_s2 * dt,
    )
    theta_dot = _clip(
        theta_dot,
        -crane_config.model.slew_speed_max_rad_s,
        crane_config.model.slew_speed_max_rad_s,
    )
    theta_ddot = (theta_dot - previous_state.theta_dot_rad_s) / dt
    theta = previous_state.theta_rad + theta_dot * dt

    trolley_v = _clip(
        target_trolley,
        -crane_config.model.trolley_speed_max_m_s,
        crane_config.model.trolley_speed_max_m_s,
    )
    trolley_r = previous_state.trolley_r_m + trolley_v * dt
    trolley_r_clamped = _clip(
        trolley_r,
        crane_config.trolley_r_min_m,
        crane_config.trolley_r_max_m,
    )
    if trolley_r_clamped != trolley_r:
        trolley_v = 0.0

    hoist_v = _clip(
        target_hoist,
        -crane_config.model.hoist_speed_max_m_s,
        crane_config.model.hoist_speed_max_m_s,
    )
    hook_h = previous_state.hook_h_m + hoist_v * dt
    hook_h_clamped = _clip(
        hook_h,
        crane_config.hook_h_min_world_m,
        crane_config.hook_h_max_world_m,
    )
    if hook_h_clamped != hook_h:
        hoist_v = 0.0

    next_state = previous_state.model_copy(
        update={
            "theta_rad": theta,
            "theta_dot_rad_s": theta_dot,
            "theta_ddot_rad_s2": theta_ddot,
            "trolley_r_m": trolley_r_clamped,
            "trolley_v_m_s": trolley_v,
            "hook_h_m": hook_h_clamped,
            "hoist_v_m_s": hoist_v,
        }
    )
    return recompute_state_geometry(crane_config, next_state)


def step_world(
    crane_configs: Sequence[CraneConfig],
    previous_states: Sequence[CraneState],
    control_targets: Sequence[ControlTarget],
    dt: float,
) -> list[CraneState]:
    state_by_id = _index_by_crane_id(
        previous_states,
        item_name="previous_state",
        field_path="previous_states",
    )
    target_by_id = _index_by_crane_id(
        control_targets,
        item_name="control_target",
        field_path="control_targets",
    )

    config_ids = {crane_config.crane_id for crane_config in crane_configs}
    for crane_id in state_by_id:
        if crane_id not in config_ids:
            raise PhysicsWorldError(
                f"unknown previous state crane_id: {crane_id}",
                reason="unknown_previous_state",
                crane_id=crane_id,
                field_path="previous_states",
            )
    for crane_id in target_by_id:
        if crane_id not in config_ids:
            raise PhysicsWorldError(
                f"unknown control target crane_id: {crane_id}",
                reason="unknown_control_target",
                crane_id=crane_id,
                field_path="control_targets",
            )

    next_states: list[CraneState] = []
    for crane_config in crane_configs:
        crane_id = crane_config.crane_id
        previous_state = state_by_id.get(crane_id)
        if previous_state is None:
            raise PhysicsWorldError(
                f"missing previous state for crane_id: {crane_id}",
                reason="missing_previous_state",
                crane_id=crane_id,
                field_path="previous_states",
            )
        control_target = target_by_id.get(crane_id)
        if control_target is None:
            raise PhysicsWorldError(
                f"missing control target for crane_id: {crane_id}",
                reason="missing_control_target",
                crane_id=crane_id,
                field_path="control_targets",
            )
        next_states.append(
            step_crane_state(crane_config, previous_state, control_target, dt)
        )
    return next_states


def _approach(current: float, target: float, max_delta: float) -> float:
    if current < target:
        return min(current + max_delta, target)
    if current > target:
        return max(current - max_delta, target)
    return current


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _index_by_crane_id(
    items: Sequence[T],
    *,
    item_name: str,
    field_path: str,
) -> Dict[str, T]:
    indexed: Dict[str, T] = {}
    for item in items:
        crane_id = getattr(item, "crane_id")
        if crane_id in indexed:
            raise PhysicsWorldError(
                f"duplicate {item_name} crane_id: {crane_id}",
                reason=f"duplicate_{item_name}",
                crane_id=crane_id,
                field_path=field_path,
            )
        indexed[crane_id] = item
    return indexed
