from __future__ import annotations

import math
from typing import Sequence

from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.state import CraneState


def initialize_crane_state(crane_config: CraneConfig) -> CraneState:
    theta_rad = crane_config.theta_init_rad
    theta_sin = math.sin(theta_rad)
    theta_cos = math.cos(theta_rad)
    hook_h_m = crane_config.hook_h_max_world_m
    trolley_r_m = crane_config.trolley_r_min_m
    return CraneState(
        crane_id=crane_config.crane_id,
        theta_rad=theta_rad,
        theta_dot_rad_s=0.0,
        theta_ddot_rad_s2=0.0,
        theta_sin=theta_sin,
        theta_cos=theta_cos,
        trolley_r_m=trolley_r_m,
        trolley_v_m_s=0.0,
        hook_h_m=hook_h_m,
        hoist_v_m_s=0.0,
        root_position=[float(value) for value in crane_config.root],
        tip_position=[
            crane_config.root[0] + crane_config.jib_length_m * theta_cos,
            crane_config.root[1] + crane_config.jib_length_m * theta_sin,
            crane_config.root[2],
        ],
        hook_position=[
            crane_config.base[0] + trolley_r_m * theta_cos,
            crane_config.base[1] + trolley_r_m * theta_sin,
            hook_h_m,
        ],
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


def initialize_world_state(crane_configs: Sequence[CraneConfig]) -> list[CraneState]:
    return [initialize_crane_state(crane_config) for crane_config in crane_configs]
