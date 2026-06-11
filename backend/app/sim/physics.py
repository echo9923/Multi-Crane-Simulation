from __future__ import annotations

import math
from typing import Sequence

from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.state import CraneState


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
