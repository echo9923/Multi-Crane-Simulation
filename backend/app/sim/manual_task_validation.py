from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.config import ManualTaskInput, ScenarioConfig, ZoneConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.sim.layout_geometry import horizontal_distance
from backend.app.sim.task_generation import resolve_zone_vertical_semantics


class ManualTaskValidationTaskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    crane_id: Optional[str] = None
    pickup_zone_id: str
    dropoff_zone_id: str
    load_type: str
    priority: str
    pickup_reachable: bool = False
    dropoff_reachable: bool = False
    pickup_radius_m: Optional[float] = None
    dropoff_radius_m: Optional[float] = None
    pickup_height_m: Optional[float] = None
    dropoff_height_m: Optional[float] = None
    required_transport_height_m: Optional[float] = None
    capacity_margin_t: Optional[float] = None
    blocking_reasons: List[str] = Field(default_factory=list)


class ManualTaskValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    task_count: int
    expected_task_count: Optional[int] = None
    task_reports: List[ManualTaskValidationTaskReport]
    warnings: List[Dict[str, object]] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)


def validate_manual_task_plan(
    scenario: ScenarioConfig,
    crane_configs: Sequence[CraneConfig],
) -> ManualTaskValidationReport:
    task_templates = list(scenario.tasks.manual_tasks or [])
    crane_by_id = {crane.crane_id: crane for crane in crane_configs}
    material_by_id = {zone.zone_id: zone for zone in scenario.site.material_zones}
    work_by_id = {zone.zone_id: zone for zone in scenario.site.work_zones}
    reports = [
        _validate_manual_task(
            template,
            scenario,
            crane_by_id=crane_by_id,
            material_by_id=material_by_id,
            work_by_id=work_by_id,
        )
        for template in task_templates
    ]
    blocking_reasons: List[str] = []
    for report in reports:
        for reason in report.blocking_reasons:
            if reason not in blocking_reasons:
                blocking_reasons.append(reason)

    expected = len(crane_configs) * scenario.tasks.num_tasks_per_crane
    warnings: List[Dict[str, object]] = []
    if len(task_templates) != expected:
        warnings.append(
            {
                "reason": (
                    "manual_task_count_below_num_tasks_per_crane_hint"
                    if len(task_templates) < expected
                    else "manual_task_count_exceeds_num_tasks_per_crane_hint"
                ),
                "expected": expected,
                "actual": len(task_templates),
                "num_cranes": len(crane_configs),
                "num_tasks_per_crane": scenario.tasks.num_tasks_per_crane,
            }
        )

    return ManualTaskValidationReport(
        valid=not blocking_reasons and bool(task_templates),
        task_count=len(task_templates),
        expected_task_count=expected,
        task_reports=reports,
        warnings=warnings,
        blocking_reasons=blocking_reasons,
    )


def _validate_manual_task(
    template: ManualTaskInput,
    scenario: ScenarioConfig,
    *,
    crane_by_id: Dict[str, CraneConfig],
    material_by_id: Dict[str, ZoneConfig],
    work_by_id: Dict[str, ZoneConfig],
) -> ManualTaskValidationTaskReport:
    blocking: List[str] = []
    crane = None
    if template.crane_id is None:
        blocking.append("invalid_task_assignment")
    else:
        crane = crane_by_id.get(template.crane_id)
        if crane is None:
            blocking.append("unknown_crane_id")

    pickup_zone = material_by_id.get(template.pickup_zone_id)
    if pickup_zone is None:
        blocking.append("unknown_pickup_zone")
    dropoff_zone = work_by_id.get(template.dropoff_zone_id)
    if dropoff_zone is None:
        blocking.append("unknown_dropoff_zone")

    load_config = scenario.load_types.get(template.load_type)
    if load_config is None:
        blocking.append("unknown_load_type")

    if (
        pickup_zone is not None
        and pickup_zone.load_types is not None
        and template.load_type not in pickup_zone.load_types
    ):
        blocking.append("pickup_load_type_not_supported")
    if (
        dropoff_zone is not None
        and dropoff_zone.accepted_load_types is not None
        and template.load_type not in dropoff_zone.accepted_load_types
    ):
        blocking.append("dropoff_load_type_not_accepted")

    pickup_point: Optional[List[float]] = None
    dropoff_point: Optional[List[float]] = None
    pickup_height = None
    dropoff_height = None
    required_transport_height = None
    pickup_radius = None
    dropoff_radius = None
    pickup_reachable = False
    dropoff_reachable = False
    capacity_margin = None

    if crane is not None and pickup_zone is not None and dropoff_zone is not None and load_config is not None:
        pickup_point = _zone_representative_hook_point(
            pickup_zone,
            load_config.size_m,
            fallback_z=scenario.tasks.fallback_pickup_z_m,
            zone_type="material",
        )
        dropoff_point = _zone_representative_hook_point(
            dropoff_zone,
            load_config.size_m,
            fallback_z=sum(scenario.tasks.fallback_dropoff_z_range_m) / 2.0,
            zone_type="work",
        )
        pickup_height = pickup_point[2]
        dropoff_height = dropoff_point[2]
        pickup_approach_height = pickup_point[3]
        dropoff_approach_height = dropoff_point[3]
        required_transport_height = max(
            pickup_approach_height,
            dropoff_approach_height,
            scenario.tasks.state_machine.safe_transport_height_m,
        )
        pickup_radius = horizontal_distance(crane.base, pickup_point)
        dropoff_radius = horizontal_distance(crane.base, dropoff_point)

        pickup_radius_ok = crane.trolley_r_min_m <= pickup_radius <= crane.trolley_r_max_m
        dropoff_radius_ok = crane.trolley_r_min_m <= dropoff_radius <= crane.trolley_r_max_m
        pickup_height_ok = crane.hook_h_min_world_m <= pickup_height <= crane.hook_h_max_world_m
        dropoff_height_ok = crane.hook_h_min_world_m <= dropoff_height <= crane.hook_h_max_world_m
        transport_height_ok = (
            crane.hook_h_min_world_m
            <= required_transport_height
            <= crane.hook_h_max_world_m
        )
        if not pickup_radius_ok:
            blocking.append("pickup_out_of_radius")
        if not dropoff_radius_ok:
            blocking.append("dropoff_out_of_radius")
        if not pickup_height_ok:
            blocking.append("pickup_out_of_hook_height")
        if not dropoff_height_ok:
            blocking.append("dropoff_out_of_hook_height")
        if not transport_height_ok:
            blocking.append("transport_out_of_hook_height")

        pickup_reachable = pickup_radius_ok and pickup_height_ok
        dropoff_reachable = dropoff_radius_ok and dropoff_height_ok
        max_weight_t = load_config.weight_range_t[1]
        pickup_margin = crane.model.capacity_at_radius_t(pickup_radius) - max_weight_t
        dropoff_margin = crane.model.capacity_at_radius_t(dropoff_radius) - max_weight_t
        capacity_margin = min(pickup_margin, dropoff_margin)
        if capacity_margin < 0:
            blocking.append("load_over_capacity")

    return ManualTaskValidationTaskReport(
        task_id=template.task_id,
        crane_id=template.crane_id,
        pickup_zone_id=template.pickup_zone_id,
        dropoff_zone_id=template.dropoff_zone_id,
        load_type=template.load_type,
        priority=template.priority.value,
        pickup_reachable=pickup_reachable,
        dropoff_reachable=dropoff_reachable,
        pickup_radius_m=_rounded(pickup_radius),
        dropoff_radius_m=_rounded(dropoff_radius),
        pickup_height_m=_rounded(pickup_height),
        dropoff_height_m=_rounded(dropoff_height),
        required_transport_height_m=_rounded(required_transport_height),
        capacity_margin_t=_rounded(capacity_margin),
        blocking_reasons=blocking,
    )


def _zone_representative_hook_point(
    zone: ZoneConfig,
    load_size_m: Sequence[float],
    *,
    fallback_z: float,
    zone_type: str,
) -> List[float]:
    if zone.center is not None:
        x, y = zone.center[0], zone.center[1]
    elif zone.points:
        x = sum(point[0] for point in zone.points) / len(zone.points)
        y = sum(point[1] for point in zone.points) / len(zone.points)
    else:
        x, y = 0.0, 0.0
    semantics = resolve_zone_vertical_semantics(
        zone,
        load_size_m,
        fallback_z=fallback_z,
        zone_type=zone_type,
        rng=random.Random(0),
    )
    return [
        float(x),
        float(y),
        float(semantics.hook_target_z_m),
        float(semantics.approach_z_m),
    ]


def _rounded(value: Optional[float]) -> Optional[float]:
    return round(value, 6) if value is not None else None
