from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, TypeVar

from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.state import PHYSICS_SCHEMA_VERSION, CraneState

T = TypeVar("T")
NUMERIC_TOLERANCE = 1e-6


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


class PhysicsStateError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        crane_id: str,
        field_path: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = "episode_failed"
        self.episode_status = "failed_invalid_state"
        self.crane_id = crane_id
        self.field_path = field_path
        self.details = details or {}


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


def build_physics_frame(
    *,
    frame_index: int,
    time_s: float,
    states: Sequence[CraneState],
) -> dict[str, object]:
    return {
        "schema_version": PHYSICS_SCHEMA_VERSION,
        "frame_index": frame_index,
        "time_s": time_s,
        "states": [state.model_dump(mode="json") for state in states],
    }


def crane_state_to_trajectory_row(
    state: CraneState,
    *,
    frame_index: int,
    time_s: float,
) -> dict[str, object]:
    load_x, load_y, load_z = _optional_xyz(state.load_position)
    return {
        "schema_version": PHYSICS_SCHEMA_VERSION,
        "frame_index": frame_index,
        "time_s": time_s,
        "crane_id": state.crane_id,
        "theta_rad": state.theta_rad,
        "theta_dot_rad_s": state.theta_dot_rad_s,
        "theta_ddot_rad_s2": state.theta_ddot_rad_s2,
        "theta_sin": state.theta_sin,
        "theta_cos": state.theta_cos,
        "trolley_r_m": state.trolley_r_m,
        "trolley_v_m_s": state.trolley_v_m_s,
        "hook_h_m": state.hook_h_m,
        "hoist_v_m_s": state.hoist_v_m_s,
        "root_x_m": state.root_position[0],
        "root_y_m": state.root_position[1],
        "root_z_m": state.root_position[2],
        "tip_x_m": state.tip_position[0],
        "tip_y_m": state.tip_position[1],
        "tip_z_m": state.tip_position[2],
        "hook_x_m": state.hook_position[0],
        "hook_y_m": state.hook_position[1],
        "hook_z_m": state.hook_position[2],
        "cable_length_m": state.cable_length_m,
        "load_x_m": load_x,
        "load_y_m": load_y,
        "load_z_m": load_z,
        "load_attached": state.load_attached,
        "load_type": state.load_type,
        "load_weight_t": state.load_weight_t,
        "swing_angle_rad": state.swing_angle_rad,
        "swing_velocity_rad_s": state.swing_velocity_rad_s,
        "task_id": state.task_id,
        "task_stage": state.task_stage,
    }


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
    _validate_dt(crane_config, dt)
    validate_crane_state(crane_config, previous_state)

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
    _validate_requested_axis_delta(
        crane_config,
        previous_state.crane_id,
        field_path="trolley_r_m",
        requested_delta=abs(trolley_v * dt),
        span=crane_config.trolley_r_max_m - crane_config.trolley_r_min_m,
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
    _validate_requested_axis_delta(
        crane_config,
        previous_state.crane_id,
        field_path="hook_h_m",
        requested_delta=abs(hoist_v * dt),
        span=crane_config.hook_h_max_world_m - crane_config.hook_h_min_world_m,
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
    next_state = recompute_state_geometry(crane_config, next_state)
    validate_crane_state(crane_config, next_state)
    _validate_state_jump(crane_config, previous_state, next_state, dt)
    return next_state


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


def _optional_xyz(value: Optional[Sequence[float]]) -> tuple[object, object, object]:
    if value is None:
        return None, None, None
    return value[0], value[1], value[2]


def validate_crane_state(
    crane_config: CraneConfig,
    state: CraneState,
    *,
    tolerance: float = NUMERIC_TOLERANCE,
) -> None:
    numeric_fields = {
        "theta_rad": state.theta_rad,
        "theta_dot_rad_s": state.theta_dot_rad_s,
        "theta_ddot_rad_s2": state.theta_ddot_rad_s2,
        "theta_sin": state.theta_sin,
        "theta_cos": state.theta_cos,
        "trolley_r_m": state.trolley_r_m,
        "trolley_v_m_s": state.trolley_v_m_s,
        "hook_h_m": state.hook_h_m,
        "hoist_v_m_s": state.hoist_v_m_s,
        "cable_length_m": state.cable_length_m,
    }
    for field, values in {
        "root_position": state.root_position,
        "tip_position": state.tip_position,
        "hook_position": state.hook_position,
        "load_position": state.load_position or [],
        "load_size_m": state.load_size_m or [],
    }.items():
        for index, value in enumerate(values):
            numeric_fields[f"{field}[{index}]"] = value

    for field_path, value in numeric_fields.items():
        if not math.isfinite(value):
            raise _state_error(
                "PHYS_E_001",
                state.crane_id,
                field_path,
                value=value,
                reason="non_finite",
            )

    _validate_range(
        state,
        "trolley_r_m",
        state.trolley_r_m,
        crane_config.trolley_r_min_m,
        crane_config.trolley_r_max_m,
        tolerance,
    )
    if state.hook_h_m > crane_config.root[2] + tolerance:
        raise _state_error(
            "PHYS_E_002",
            state.crane_id,
            "hook_h_m",
            value=state.hook_h_m,
            limit=crane_config.root[2],
            reason="hook_above_root",
        )
    _validate_range(
        state,
        "hook_h_m",
        state.hook_h_m,
        crane_config.hook_h_min_world_m,
        crane_config.hook_h_max_world_m,
        tolerance,
    )
    _validate_range(
        state,
        "cable_length_m",
        state.cable_length_m,
        crane_config.cable_length_min_m,
        crane_config.cable_length_max_m,
        tolerance,
    )
    expected_cable = crane_config.root[2] - state.hook_h_m
    if abs(state.cable_length_m - expected_cable) > tolerance:
        raise _state_error(
            "PHYS_E_002",
            state.crane_id,
            "cable_length_m",
            value=state.cable_length_m,
            expected=expected_cable,
            reason="cable_length_inconsistent",
        )
    if abs(state.theta_sin - math.sin(state.theta_rad)) > tolerance:
        raise _state_error(
            "PHYS_E_002",
            state.crane_id,
            "theta_sin",
            value=state.theta_sin,
            expected=math.sin(state.theta_rad),
            reason="theta_trig_inconsistent",
        )
    if abs(state.theta_cos - math.cos(state.theta_rad)) > tolerance:
        raise _state_error(
            "PHYS_E_002",
            state.crane_id,
            "theta_cos",
            value=state.theta_cos,
            expected=math.cos(state.theta_rad),
            reason="theta_trig_inconsistent",
        )


def _validate_dt(crane_config: CraneConfig, dt: float) -> None:
    if not math.isfinite(dt):
        raise _state_error(
            "PHYS_E_001",
            crane_config.crane_id,
            "dt",
            value=dt,
            reason="non_finite",
        )
    if dt <= 0:
        raise _state_error(
            "PHYS_E_002",
            crane_config.crane_id,
            "dt",
            value=dt,
            reason="non_positive_dt",
        )


def _validate_range(
    state: CraneState,
    field_path: str,
    value: float,
    lower: float,
    upper: float,
    tolerance: float,
) -> None:
    if value < lower - tolerance or value > upper + tolerance:
        raise _state_error(
            "PHYS_E_002",
            state.crane_id,
            field_path,
            value=value,
            limit=[lower, upper],
            reason="out_of_range",
        )


def _validate_state_jump(
    crane_config: CraneConfig,
    previous_state: CraneState,
    next_state: CraneState,
    dt: float,
) -> None:
    max_trolley_delta = crane_config.model.trolley_speed_max_m_s * dt + NUMERIC_TOLERANCE
    trolley_delta = abs(next_state.trolley_r_m - previous_state.trolley_r_m)
    if trolley_delta > max_trolley_delta:
        raise _state_error(
            "PHYS_E_002",
            next_state.crane_id,
            "trolley_r_m",
            value=trolley_delta,
            limit=max_trolley_delta,
            reason="abnormal_state_jump",
        )

    max_hook_delta = crane_config.model.hoist_speed_max_m_s * dt + NUMERIC_TOLERANCE
    hook_delta = abs(next_state.hook_h_m - previous_state.hook_h_m)
    if hook_delta > max_hook_delta:
        raise _state_error(
            "PHYS_E_002",
            next_state.crane_id,
            "hook_h_m",
            value=hook_delta,
            limit=max_hook_delta,
            reason="abnormal_state_jump",
        )


def _validate_requested_axis_delta(
    crane_config: CraneConfig,
    crane_id: str,
    *,
    field_path: str,
    requested_delta: float,
    span: float,
) -> None:
    if requested_delta > span + NUMERIC_TOLERANCE:
        raise _state_error(
            "PHYS_E_002",
            crane_id,
            field_path,
            value=requested_delta,
            limit=span,
            reason="abnormal_state_jump",
        )


def _state_error(
    error_code: str,
    crane_id: str,
    field_path: str,
    **details: Any,
) -> PhysicsStateError:
    reason = details.get("reason", "invalid_state")
    return PhysicsStateError(
        f"{error_code} {field_path}: {reason}",
        error_code=error_code,
        crane_id=crane_id,
        field_path=field_path,
        details=details,
    )


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
