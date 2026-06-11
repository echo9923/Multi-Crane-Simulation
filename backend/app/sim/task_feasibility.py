from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.config import ScenarioConfig, ZoneConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.task import Task, TaskPoint
from backend.app.sim.layout_geometry import (
    horizontal_distance,
    point_in_boundary,
    point_in_zone,
)


class TaskFeasibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    crane_id: str
    feasible: bool
    pickup_reachable: bool
    dropoff_reachable: bool
    boundary_clear: bool
    forbidden_zone_clear: bool
    load_type_supported: bool
    pickup_capacity_margin_t: Optional[float] = None
    dropoff_capacity_margin_t: Optional[float] = None
    blocking_error_code: Optional[str] = None
    blocking_reasons: List[str] = Field(default_factory=list)
    warnings: List[Dict[str, object]] = Field(default_factory=list)


def validate_task_feasibility(
    task: Task,
    crane: CraneConfig,
    scenario: ScenarioConfig,
) -> TaskFeasibilityReport:
    blocking_reasons: List[str] = []
    pickup_reachable = _point_reachable(
        task.pickup,
        crane,
        prefix="pickup",
        blocking_reasons=blocking_reasons,
    )
    dropoff_reachable = _point_reachable(
        task.dropoff,
        crane,
        prefix="dropoff",
        blocking_reasons=blocking_reasons,
    )

    boundary_clear = True
    if not point_in_boundary(task.pickup.as_xyz(), scenario.site.boundary):
        boundary_clear = False
        blocking_reasons.append("pickup_outside_site_boundary")
    if not point_in_boundary(task.dropoff.as_xyz(), scenario.site.boundary):
        boundary_clear = False
        blocking_reasons.append("dropoff_outside_site_boundary")

    forbidden_zone_clear = True
    for zone in scenario.site.forbidden_zones:
        if point_in_zone(task.pickup.as_xyz(), zone):
            forbidden_zone_clear = False
            blocking_reasons.append("pickup_inside_forbidden_zone")
        if point_in_zone(task.dropoff.as_xyz(), zone):
            forbidden_zone_clear = False
            blocking_reasons.append("dropoff_inside_forbidden_zone")

    material_zones = {zone.zone_id: zone for zone in scenario.site.material_zones}
    work_zones = {zone.zone_id: zone for zone in scenario.site.work_zones}
    pickup_zone = material_zones.get(task.pickup_zone_id)
    dropoff_zone = work_zones.get(task.dropoff_zone_id)

    load_type_supported = _validate_load_type_support(
        task,
        scenario,
        pickup_zone,
        dropoff_zone,
        blocking_reasons,
    )

    pickup_margin = _capacity_margin(task, crane, task.pickup)
    dropoff_margin = _capacity_margin(task, crane, task.dropoff)
    if pickup_margin < 0:
        blocking_reasons.append("pickup_over_capacity")
    if dropoff_margin < 0:
        blocking_reasons.append("dropoff_over_capacity")

    blocking_error_code = _blocking_error_code(blocking_reasons)
    return TaskFeasibilityReport(
        task_id=task.task_id,
        crane_id=task.crane_id,
        feasible=blocking_error_code is None,
        pickup_reachable=pickup_reachable,
        dropoff_reachable=dropoff_reachable,
        boundary_clear=boundary_clear,
        forbidden_zone_clear=forbidden_zone_clear,
        load_type_supported=load_type_supported,
        pickup_capacity_margin_t=round(pickup_margin, 6),
        dropoff_capacity_margin_t=round(dropoff_margin, 6),
        blocking_error_code=blocking_error_code,
        blocking_reasons=blocking_reasons,
        warnings=[],
    )


def _point_reachable(
    point: TaskPoint,
    crane: CraneConfig,
    *,
    prefix: str,
    blocking_reasons: List[str],
) -> bool:
    reachable = True
    radius = horizontal_distance(crane.base, point.as_xyz())
    if radius < crane.trolley_r_min_m or radius > crane.trolley_r_max_m:
        reachable = False
        blocking_reasons.append(f"{prefix}_outside_radius")
    if point.z < crane.hook_h_min_world_m or point.z > crane.hook_h_max_world_m:
        reachable = False
        blocking_reasons.append(f"{prefix}_height_unreachable")
    return reachable


def _validate_load_type_support(
    task: Task,
    scenario: ScenarioConfig,
    pickup_zone: Optional[ZoneConfig],
    dropoff_zone: Optional[ZoneConfig],
    blocking_reasons: List[str],
) -> bool:
    supported = True
    if pickup_zone is None:
        supported = False
        blocking_reasons.append("unknown_pickup_zone")
    if dropoff_zone is None:
        supported = False
        blocking_reasons.append("unknown_dropoff_zone")
    if task.load_type not in scenario.load_types:
        supported = False
        blocking_reasons.append("unknown_load_type")
        return supported
    if (
        pickup_zone is not None
        and pickup_zone.load_types is not None
        and task.load_type not in pickup_zone.load_types
    ):
        supported = False
        blocking_reasons.append("pickup_zone_rejects_load_type")
    if (
        dropoff_zone is not None
        and dropoff_zone.accepted_load_types is not None
        and task.load_type not in dropoff_zone.accepted_load_types
    ):
        supported = False
        blocking_reasons.append("dropoff_zone_rejects_load_type")
    return supported


def _capacity_margin(task: Task, crane: CraneConfig, point: TaskPoint) -> float:
    radius = horizontal_distance(crane.base, point.as_xyz())
    capacity = crane.model.capacity_at_radius_t(radius)
    return capacity - task.load_weight_t


def _blocking_error_code(blocking_reasons: List[str]) -> Optional[str]:
    if not blocking_reasons:
        return None
    if all(reason.endswith("_over_capacity") for reason in blocking_reasons):
        return "TASK_E_002"
    return "TASK_E_001"
