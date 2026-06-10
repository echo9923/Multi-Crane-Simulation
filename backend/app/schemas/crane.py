from __future__ import annotations

import math
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CraneBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoadChartPoint(CraneBaseModel):
    radius_m: float = Field(gt=0)
    capacity_t: float = Field(gt=0)


class CraneModelSpec(CraneBaseModel):
    schema_version: str = "1.0"
    model_id: str
    jib_length_m: float = Field(gt=0)
    counter_jib_length_m: float = Field(gt=0)
    mast_height_range_m: List[float]
    max_load_t: float = Field(gt=0)
    max_load_radius_m: float = Field(gt=0)
    tip_load_t: float = Field(gt=0)
    rated_moment_t_m: float = Field(gt=0)
    slew_speed_max_rad_s: float = Field(gt=0)
    slew_acc_max_rad_s2: float = Field(gt=0)
    trolley_r_min_m: float = Field(ge=0)
    trolley_r_max_m: float = Field(gt=0)
    trolley_speed_max_m_s: float = Field(gt=0)
    cable_length_min_m: float = Field(ge=0)
    cable_length_max_m: float = Field(gt=0)
    hoist_speed_max_m_s: float = Field(gt=0)
    min_clearance_below_jib_m: float = Field(ge=0)
    load_chart_points: Optional[List[LoadChartPoint]] = None
    source: Literal["builtin", "yaml_override", "yaml_new"]

    @field_validator("mast_height_range_m")
    @classmethod
    def validate_mast_height_range(cls, value: List[float]) -> List[float]:
        if len(value) != 2 or value[0] > value[1]:
            raise ValueError("mast_height_range_m must contain [min, max]")
        return value

    @model_validator(mode="after")
    def validate_constraints(self) -> "CraneModelSpec":
        if self.trolley_r_min_m > self.trolley_r_max_m:
            raise ValueError("trolley_r_min_m must be <= trolley_r_max_m")
        if self.cable_length_min_m > self.cable_length_max_m:
            raise ValueError("cable_length_min_m must be <= cable_length_max_m")
        if self.max_load_radius_m > self.jib_length_m:
            raise ValueError("max_load_radius_m must be <= jib_length_m")
        if self.trolley_r_max_m > self.jib_length_m:
            raise ValueError("trolley_r_max_m must be <= jib_length_m")
        if self.tip_load_t > self.max_load_t:
            raise ValueError("tip_load_t must be <= max_load_t")
        if self.load_chart_points:
            radii = [point.radius_m for point in self.load_chart_points]
            if any(left >= right for left, right in zip(radii, radii[1:])):
                raise ValueError("load_chart_points radius_m values must increase")
        return self

    def capacity_at_radius_t(self, radius_m: float) -> float:
        if radius_m > self.jib_length_m:
            return 0.0
        chart_capacity = self._chart_capacity_at_radius(radius_m)
        moment_radius = max(radius_m, self.trolley_r_min_m)
        moment_capacity = self.rated_moment_t_m / moment_radius
        return max(0.0, min(chart_capacity, moment_capacity))

    def is_load_allowed(self, load_weight_t: float, trolley_r_m: float) -> bool:
        return load_weight_t <= self.capacity_at_radius_t(trolley_r_m)

    def moment_at_radius_t_m(self, load_weight_t: float, trolley_r_m: float) -> float:
        return load_weight_t * trolley_r_m

    def _chart_capacity_at_radius(self, radius_m: float) -> float:
        if self.load_chart_points:
            return _interpolate_chart(
                radius_m,
                [(point.radius_m, point.capacity_t) for point in self.load_chart_points],
            )
        if radius_m <= self.max_load_radius_m:
            return self.max_load_t
        return _linear_interpolate(
            radius_m,
            self.max_load_radius_m,
            self.jib_length_m,
            self.max_load_t,
            self.tip_load_t,
        )


def crane_model_spec_from_config(
    payload: object,
    *,
    source: Literal["builtin", "yaml_override", "yaml_new"],
) -> CraneModelSpec:
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    elif isinstance(payload, dict):
        data = dict(payload)
    else:
        raise TypeError("crane model payload must be a dict or pydantic model")
    speed_deg = data.pop("slew_speed_max_deg_s")
    acc_deg = data.pop("slew_acc_max_deg_s2")
    data["slew_speed_max_rad_s"] = math.radians(speed_deg)
    data["slew_acc_max_rad_s2"] = math.radians(acc_deg)
    data["source"] = source
    return CraneModelSpec.model_validate(data)


def _linear_interpolate(
    radius_m: float,
    left_radius: float,
    right_radius: float,
    left_capacity: float,
    right_capacity: float,
) -> float:
    if right_radius == left_radius:
        return min(left_capacity, right_capacity)
    t = (radius_m - left_radius) / (right_radius - left_radius)
    return left_capacity + t * (right_capacity - left_capacity)


def _interpolate_chart(radius_m: float, chart: List[Tuple[float, float]]) -> float:
    if radius_m <= chart[0][0]:
        return chart[0][1]
    for left, right in zip(chart, chart[1:]):
        if left[0] <= radius_m <= right[0]:
            return _linear_interpolate(radius_m, left[0], right[0], left[1], right[1])
    return chart[-1][1]


CraneModelLibrary = Dict[str, CraneModelSpec]


class CraneConfig(CraneBaseModel):
    schema_version: str = "1.0"
    crane_id: str
    model_id: str
    model: CraneModelSpec
    base: List[float]
    root: List[float]
    mast_height_m: float
    jib_length_m: float
    counter_jib_length_m: float
    trolley_r_min_m: float
    trolley_r_max_m: float
    hook_h_min_world_m: float
    hook_h_max_world_m: float
    cable_length_min_m: float
    cable_length_max_m: float
    theta_init_rad: float
    theta_init_deg: float
    theta_sin: float
    theta_cos: float
    slew_mode: Literal["continuous", "limited"]
    theta_limit_rad: Optional[List[float]] = None
    source: Literal["manual", "auto"]


class CranePairLayoutDiagnostic(CraneBaseModel):
    crane_id_a: str
    crane_id_b: str
    root_distance_m: float
    base_distance_m: float
    height_delta_m: float
    work_radius_overlap_area_m2: float
    work_radius_union_area_m2: float
    overlap_ratio: float


class LayoutDiagnostics(CraneBaseModel):
    mode: str
    num_cranes: int
    quality_score: Optional[float] = None
    overlap_target_score: Optional[float] = None
    coverage_score: Optional[float] = None
    height_strategy_score: Optional[float] = None
    boundary_margin_score: Optional[float] = None
    pair_diagnostics: List[CranePairLayoutDiagnostic]
    warnings: List[dict] = Field(default_factory=list)
