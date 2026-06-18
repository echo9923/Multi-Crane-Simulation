from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.config import ScenarioConfig, ZoneConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.enums import QueueStartMode, TaskGenerationMode
from backend.app.schemas.task import (
    Task,
    TaskGenerationReport,
    TaskPoint,
    TaskQueue,
)
from backend.app.sim.layout_geometry import (
    circle_intersection_area,
    horizontal_distance,
    point_in_boundary,
    point_in_zone,
)


class TaskGenerationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        reason: str,
        details: Optional[Dict[str, object]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.reason = reason
        self.details = details or {}


class TaskGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queues: List[TaskQueue]
    tasks: List[Task]
    report: TaskGenerationReport


@dataclass(frozen=True)
class TaskOverlapRegion:
    region_id: str
    crane_ids: List[str]
    approximate_center_xy: Tuple[float, float]
    candidate_material_zone_ids: List[str]
    candidate_work_zone_ids: List[str]


@dataclass(frozen=True)
class ZoneVerticalSemantics:
    surface_z_m: float
    load_center_z_m: float
    hook_target_z_m: float
    approach_z_m: float


def generate_task_queues(
    scenario: ScenarioConfig,
    crane_configs: Sequence[CraneConfig],
    *,
    seed: int,
) -> TaskGenerationResult:
    if not scenario.site.material_zones or not scenario.site.work_zones:
        raise TaskGenerationError(
            "task generation requires material and work zones",
            error_code="TASK_E_001",
            reason="missing_material_or_work_zones",
        )

    cranes = sorted(crane_configs, key=lambda crane: crane.crane_id)
    rng = random.Random(seed)
    overlap_regions = derive_task_overlap_regions(
        cranes,
        scenario.site.material_zones,
        scenario.site.work_zones,
    )
    if _requires_overlap_only(scenario) and not overlap_regions:
        raise TaskGenerationError(
            "overlap_task or stress_task requires at least one task overlap region",
            error_code="TASK_E_001",
            reason="no_task_overlap_region",
        )

    queues = [TaskQueue(crane_id=crane.crane_id) for crane in cranes]
    queue_by_crane_id = {queue.crane_id: queue for queue in queues}
    tasks: List[Task] = []
    resample_attempts = 0
    warnings: List[Dict[str, object]] = []

    if scenario.tasks.generation_mode is TaskGenerationMode.MANUAL:
        for template in scenario.tasks.manual_tasks or []:
            task, attempts = _generate_manual_task(
                scenario,
                cranes,
                template,
                rng,
                seed=seed,
            )
            resample_attempts += attempts
            queue_by_crane_id[task.crane_id].tasks.append(task)
            tasks.append(task)
    else:
        for crane in cranes:
            for index in range(1, scenario.tasks.num_tasks_per_crane + 1):
                task, attempts = _generate_auto_task(
                    scenario,
                    crane,
                    rng,
                    seed=seed,
                    task_index=index,
                    overlap_regions=overlap_regions,
                )
                resample_attempts += attempts
                queue_by_crane_id[crane.crane_id].tasks.append(task)
                tasks.append(task)

    counts: Dict[str, int] = {}
    for task in tasks:
        counts[task.task_type] = counts.get(task.task_type, 0) + 1

    return TaskGenerationResult(
        queues=queues,
        tasks=tasks,
        report=TaskGenerationReport(
            seed=seed,
            num_cranes=len(cranes),
            num_tasks_total=len(tasks),
            num_tasks_by_type=counts,
            num_resample_attempts=resample_attempts,
            warnings=warnings,
            blocking_errors=[],
        ),
    )


def derive_task_overlap_regions(
    cranes: Sequence[CraneConfig],
    material_zones: Sequence[ZoneConfig],
    work_zones: Sequence[ZoneConfig],
) -> List[TaskOverlapRegion]:
    regions: List[TaskOverlapRegion] = []
    for left_index, left in enumerate(cranes):
        for right in cranes[left_index + 1 :]:
            distance = horizontal_distance(left.base, right.base)
            overlap_area = circle_intersection_area(
                left.trolley_r_max_m,
                right.trolley_r_max_m,
                distance,
            )
            if overlap_area <= 0:
                continue
            center = ((left.base[0] + right.base[0]) / 2.0, (left.base[1] + right.base[1]) / 2.0)
            material_ids = [
                zone.zone_id
                for zone in material_zones
                if _zone_center(zone) is not None
                and _point_reachable(left, _zone_center(zone))
                and _point_reachable(right, _zone_center(zone))
            ]
            work_ids = [
                zone.zone_id
                for zone in work_zones
                if _zone_center(zone) is not None
                and _point_reachable(left, _zone_center(zone))
                and _point_reachable(right, _zone_center(zone))
            ]
            if not material_ids and not work_ids:
                continue
            regions.append(
                TaskOverlapRegion(
                    region_id=f"overlap_{left.crane_id}_{right.crane_id}",
                    crane_ids=[left.crane_id, right.crane_id],
                    approximate_center_xy=center,
                    candidate_material_zone_ids=material_ids,
                    candidate_work_zone_ids=work_ids,
                )
            )
    return regions


def _generate_auto_task(
    scenario: ScenarioConfig,
    crane: CraneConfig,
    rng: random.Random,
    *,
    seed: int,
    task_index: int,
    overlap_regions: Sequence[TaskOverlapRegion],
) -> Tuple[Task, int]:
    max_attempts = scenario.layout.max_sampling_attempts
    task_type = _sample_weighted(rng, scenario.tasks.task_type_distribution)
    if task_type in {"overlap_task", "stress_task"} and not overlap_regions:
        if _task_type_weight(scenario, "easy_task") > 0:
            task_type = "easy_task"
        else:
            raise TaskGenerationError(
                "overlap task requested but no overlap region is available",
                error_code="TASK_E_001",
                reason="no_task_overlap_region",
            )
    if task_type == "stress_task":
        task_type = "stress_task"

    for attempt in range(1, max_attempts + 1):
        try:
            task = _build_task_candidate(
                scenario,
                crane,
                rng,
                seed=seed,
                task_id=f"T_{crane.crane_id}_{task_index:03d}",
                task_type=task_type,
                task_index=task_index,
                generation_attempt=attempt,
                overlap_regions=overlap_regions,
            )
        except TaskGenerationError:
            if attempt >= max_attempts:
                raise
            continue
        return task, attempt - 1

    raise TaskGenerationError(
        "unable to generate task within maximum attempts",
        error_code="TASK_E_001",
        reason="max_sampling_attempts_exceeded",
    )


def _generate_manual_task(
    scenario: ScenarioConfig,
    cranes: Sequence[CraneConfig],
    template: object,
    rng: random.Random,
    *,
    seed: int,
) -> Tuple[Task, int]:
    feasible: List[Task] = []
    blocking_errors: List[TaskGenerationError] = []
    attempts = 0
    requested_crane_id = getattr(template, "crane_id", None)
    candidate_cranes = [
        crane
        for crane in cranes
        if requested_crane_id is None or crane.crane_id == requested_crane_id
    ]
    if not candidate_cranes and requested_crane_id is not None:
        raise TaskGenerationError(
            "unknown crane id for manual task template",
            error_code="TASK_E_001",
            reason="unknown_crane",
            details={"crane_id": requested_crane_id, "task_id": template.task_id},
        )
    for crane in candidate_cranes:
        local_seed = _stable_int(seed, template.task_id, crane.crane_id)
        local_rng = random.Random(local_seed)
        for _ in range(scenario.layout.max_sampling_attempts):
            attempts += 1
            try:
                task = _build_task_candidate(
                    scenario,
                    crane,
                    local_rng,
                    seed=seed,
                    task_id=template.task_id,
                    task_type=template.task_type.value,
                    task_index=1,
                    generation_attempt=attempts,
                    overlap_regions=[],
                    pickup_zone_id=template.pickup_zone_id,
                    dropoff_zone_id=template.dropoff_zone_id,
                    load_type=template.load_type,
                    priority=template.priority.value,
                )
            except TaskGenerationError as exc:
                if exc.reason in {
                    "point_height_unreachable",
                    "over_capacity",
                    "pickup_zone_rejects_load_type",
                    "dropoff_zone_rejects_load_type",
                    "no_supported_load_type",
                    "unknown_load_type",
                    "unknown_zone",
                }:
                    details = dict(exc.details)
                    details.setdefault("task_id", template.task_id)
                    if requested_crane_id is not None:
                        details.setdefault("requested_crane_id", requested_crane_id)
                    blocking_errors.append(
                        TaskGenerationError(
                            str(exc),
                            error_code=exc.error_code,
                            reason=exc.reason,
                            details=details,
                        )
                    )
                    break
                continue
            feasible.append(task)
            break
    if not feasible:
        if blocking_errors:
            raise blocking_errors[0]
        raise TaskGenerationError(
            "manual task template cannot be assigned to any crane",
            error_code="TASK_E_001",
            reason="manual_task_unassignable",
        )
    if len(feasible) == 1:
        return feasible[0], attempts - 1
    choice = rng.randrange(len(feasible))
    return feasible[choice], attempts - 1


def _build_task_candidate(
    scenario: ScenarioConfig,
    crane: CraneConfig,
    rng: random.Random,
    *,
    seed: int,
    task_id: str,
    task_type: str,
    task_index: int,
    generation_attempt: int,
    overlap_regions: Sequence[TaskOverlapRegion],
    pickup_zone_id: Optional[str] = None,
    dropoff_zone_id: Optional[str] = None,
    load_type: Optional[str] = None,
    priority: Optional[str] = None,
) -> Task:
    material_zone = _select_zone(
        scenario.site.material_zones,
        rng,
        zone_id=pickup_zone_id,
        task_type=task_type,
        overlap_regions=overlap_regions,
        material=True,
    )
    work_zone = _select_zone(
        scenario.site.work_zones,
        rng,
        zone_id=dropoff_zone_id,
        task_type=task_type,
        overlap_regions=overlap_regions,
        material=False,
    )
    load_type_value = load_type or _sample_load_type(scenario, material_zone, work_zone, rng)
    load_config = scenario.load_types[load_type_value]
    pickup = _sample_point(
        material_zone,
        rng,
        scenario,
        load_size_m=load_config.size_m,
        fallback_z=scenario.tasks.fallback_pickup_z_m,
        zone_type="material",
    )
    dropoff = _sample_point(
        work_zone,
        rng,
        scenario,
        load_size_m=load_config.size_m,
        fallback_z=rng.uniform(*scenario.tasks.fallback_dropoff_z_range_m),
        zone_type="work",
    )

    _validate_point_for_generation(crane, scenario, pickup, material_zone)
    _validate_point_for_generation(crane, scenario, dropoff, work_zone)
    _validate_load_zone_support(scenario, material_zone, work_zone, load_type_value)
    max_capacity = min(
        crane.model.capacity_at_radius_t(horizontal_distance(crane.base, pickup.as_xyz())),
        crane.model.capacity_at_radius_t(horizontal_distance(crane.base, dropoff.as_xyz())),
    )
    min_weight, max_weight = load_config.weight_range_t
    allowed_max = min(max_weight, max_capacity)
    if allowed_max < min_weight:
        raise TaskGenerationError(
            "task load is over crane capacity",
            error_code="TASK_E_002",
            reason="over_capacity",
            details={"task_id": task_id, "capacity_t": max_capacity},
        )
    weight = rng.uniform(min_weight, allowed_max)
    chosen_priority = priority or _sample_weighted(rng, scenario.tasks.priority_distribution)
    planned_start = _planned_start_s(scenario, rng, task_type, task_index, crane)
    deadline = _deadline_s(task_type, chosen_priority)

    return Task(
        task_id=task_id,
        crane_id=crane.crane_id,
        task_type=task_type,
        pickup=pickup,
        dropoff=dropoff,
        pickup_zone_id=material_zone.zone_id,
        dropoff_zone_id=work_zone.zone_id,
        planned_start_s=planned_start,
        load_type=load_type_value,
        load_weight_t=round(weight, 3),
        load_size_m=[float(value) for value in load_config.size_m],
        priority=chosen_priority,
        deadline_s=deadline,
        generation_seed=seed,
        generation_attempt=generation_attempt,
    )


def _sample_weighted(rng: random.Random, distribution: Dict[object, float]) -> str:
    threshold = rng.random()
    cumulative = 0.0
    last_key = None
    for key, weight in distribution.items():
        key_value = key.value if hasattr(key, "value") else str(key)
        last_key = key_value
        cumulative += weight
        if threshold <= cumulative:
            return key_value
    if last_key is None:
        raise TaskGenerationError(
            "empty distribution",
            error_code="TASK_E_001",
            reason="empty_distribution",
        )
    return last_key


def _select_zone(
    zones: Sequence[ZoneConfig],
    rng: random.Random,
    *,
    zone_id: Optional[str],
    task_type: str,
    overlap_regions: Sequence[TaskOverlapRegion],
    material: bool,
) -> ZoneConfig:
    if zone_id is not None:
        for zone in zones:
            if zone.zone_id == zone_id:
                return zone
        raise TaskGenerationError(
            "unknown zone id",
            error_code="TASK_E_001",
            reason="unknown_zone",
            details={"zone_id": zone_id},
        )
    candidates = list(zones)
    if task_type in {"overlap_task", "stress_task"} and overlap_regions:
        overlap_ids = {
            zone_id
            for region in overlap_regions
            for zone_id in (
                region.candidate_material_zone_ids
                if material
                else region.candidate_work_zone_ids
            )
        }
        overlap_candidates = [zone for zone in zones if zone.zone_id in overlap_ids]
        if overlap_candidates:
            candidates = overlap_candidates
    if not candidates:
        raise TaskGenerationError(
            "no candidate zones",
            error_code="TASK_E_001",
            reason="no_candidate_zones",
        )
    return rng.choice(candidates)


def _sample_load_type(
    scenario: ScenarioConfig,
    material_zone: ZoneConfig,
    work_zone: ZoneConfig,
    rng: random.Random,
) -> str:
    all_types = set(scenario.load_types)
    material_types = set(material_zone.load_types or all_types)
    work_types = set(work_zone.accepted_load_types or all_types)
    candidates = sorted(all_types & material_types & work_types)
    if not candidates:
        raise TaskGenerationError(
            "zone pair has no supported load type",
            error_code="TASK_E_001",
            reason="no_supported_load_type",
            details={
                "pickup_zone_id": material_zone.zone_id,
                "dropoff_zone_id": work_zone.zone_id,
            },
        )
    return rng.choice(candidates)


def _sample_point(
    zone: ZoneConfig,
    rng: random.Random,
    scenario: ScenarioConfig,
    *,
    load_size_m: Sequence[float],
    fallback_z: float,
    zone_type: str,
) -> TaskPoint:
    for _ in range(scenario.layout.max_sampling_attempts):
        if zone.type == "box" and zone.center is not None and zone.size is not None:
            x = rng.uniform(zone.center[0] - zone.size[0] / 2.0, zone.center[0] + zone.size[0] / 2.0)
            y = rng.uniform(zone.center[1] - zone.size[1] / 2.0, zone.center[1] + zone.size[1] / 2.0)
            semantics = resolve_zone_vertical_semantics(
                zone,
                load_size_m,
                fallback_z=fallback_z,
                zone_type=zone_type,
                rng=rng,
            )
            point = [
                x,
                y,
                semantics.hook_target_z_m,
            ]
        elif zone.type == "polygon" and zone.points:
            xs = [point[0] for point in zone.points]
            ys = [point[1] for point in zone.points]
            x = rng.uniform(min(xs), max(xs))
            y = rng.uniform(min(ys), max(ys))
            semantics = resolve_zone_vertical_semantics(
                zone,
                load_size_m,
                fallback_z=fallback_z,
                zone_type=zone_type,
                rng=rng,
            )
            point = [
                x,
                y,
                semantics.hook_target_z_m,
            ]
        elif zone.center is not None:
            semantics = resolve_zone_vertical_semantics(
                zone,
                load_size_m,
                fallback_z=fallback_z,
                zone_type=zone_type,
                rng=rng,
            )
            point = [zone.center[0], zone.center[1], semantics.hook_target_z_m]
        else:
            raise TaskGenerationError(
                "zone has no sampleable geometry",
                error_code="TASK_E_001",
                reason="invalid_zone_geometry",
                details={"zone_id": zone.zone_id},
            )
        surface_point = [point[0], point[1], semantics.surface_z_m]
        if point_in_zone(surface_point, zone) and point_in_boundary(point, scenario.site.boundary):
            return TaskPoint(
                x=round(point[0], 3),
                y=round(point[1], 3),
                z=round(semantics.hook_target_z_m, 3),
                zone_id=zone.zone_id,
                zone_type=zone_type,  # type: ignore[arg-type]
                surface_z_m=round(semantics.surface_z_m, 3),
                load_center_z_m=round(semantics.load_center_z_m, 3),
                hook_target_z_m=round(semantics.hook_target_z_m, 3),
                approach_z_m=round(semantics.approach_z_m, 3),
                floor_id=zone.floor_id,
                building_id=zone.building_id,
                zone_role=zone.zone_role,
            )
    raise TaskGenerationError(
        "unable to sample point inside zone and boundary",
        error_code="TASK_E_001",
        reason="point_sampling_failed",
        details={"zone_id": zone.zone_id},
    )


def _sample_z(zone: ZoneConfig, rng: random.Random, fallback_z: float) -> float:
    if zone.z_range_m is not None:
        return rng.uniform(zone.z_range_m[0], zone.z_range_m[1])
    return fallback_z


def resolve_zone_vertical_semantics(
    zone: ZoneConfig,
    load_size_m: Sequence[float],
    fallback_z: float,
    zone_type: str,
    rng: Optional[random.Random] = None,
) -> ZoneVerticalSemantics:
    del zone_type
    load_size_z = float(load_size_m[2]) if len(load_size_m) >= 3 else 0.0
    if zone.surface_z_m is not None:
        surface_z_m = float(zone.surface_z_m)
        if zone.load_center_offset_m is not None:
            load_center_z_m = surface_z_m + float(zone.load_center_offset_m)
        else:
            load_center_z_m = surface_z_m + load_size_z / 2.0
        hook_target_z_m = surface_z_m + load_size_z + zone.hook_target_offset_m
        hook_target_z_m = max(hook_target_z_m, load_center_z_m)
    else:
        # Legacy YAML used z_range_m as the sampled task point height. Preserve
        # that interpretation so old configs do not become unreachable when the
        # new construction-surface fields are absent.
        compatibility_z_m = _sample_z(zone, rng or random.Random(0), fallback_z)
        surface_z_m = compatibility_z_m
        load_center_z_m = compatibility_z_m
        hook_target_z_m = compatibility_z_m
    approach_z_m = hook_target_z_m + zone.approach_clearance_m
    return ZoneVerticalSemantics(
        surface_z_m=surface_z_m,
        load_center_z_m=load_center_z_m,
        hook_target_z_m=hook_target_z_m,
        approach_z_m=approach_z_m,
    )


def _validate_point_for_generation(
    crane: CraneConfig,
    scenario: ScenarioConfig,
    point: TaskPoint,
    zone: ZoneConfig,
) -> None:
    xyz = point.as_xyz()
    radius = horizontal_distance(crane.base, xyz)
    if not (crane.trolley_r_min_m <= radius <= crane.trolley_r_max_m):
        raise TaskGenerationError(
            "task point is outside crane radius",
            error_code="TASK_E_001",
            reason="point_outside_radius",
            details={"crane_id": crane.crane_id, "zone_id": zone.zone_id, "radius_m": radius},
        )
    hook_target_z = point.hook_target_z_m if point.hook_target_z_m is not None else point.z
    if not (crane.hook_h_min_world_m <= hook_target_z <= crane.hook_h_max_world_m):
        raise TaskGenerationError(
            "task point hook target height is unreachable",
            error_code="TASK_E_001",
            reason="point_height_unreachable",
            details={
                "crane_id": crane.crane_id,
                "zone_id": zone.zone_id,
                "height_field": "hook_target_z_m",
                "z": point.z,
                "hook_target_z_m": hook_target_z,
                "hook_h_min_world_m": crane.hook_h_min_world_m,
                "hook_h_max_world_m": crane.hook_h_max_world_m,
            },
        )
    for forbidden_zone in scenario.site.forbidden_zones:
        surface_z = point.surface_z_m if point.surface_z_m is not None else point.z
        if point_in_zone([point.x, point.y, surface_z], forbidden_zone):
            raise TaskGenerationError(
                "task point is inside forbidden zone",
                error_code="TASK_E_001",
                reason="point_inside_forbidden_zone",
                details={"zone_id": forbidden_zone.zone_id},
            )


def _validate_load_zone_support(
    scenario: ScenarioConfig,
    material_zone: ZoneConfig,
    work_zone: ZoneConfig,
    load_type: str,
) -> None:
    if load_type not in scenario.load_types:
        raise TaskGenerationError(
            "unknown load type",
            error_code="TASK_E_001",
            reason="unknown_load_type",
            details={"load_type": load_type},
        )
    if material_zone.load_types is not None and load_type not in material_zone.load_types:
        raise TaskGenerationError(
            "material zone rejects load type",
            error_code="TASK_E_001",
            reason="pickup_zone_rejects_load_type",
            details={"zone_id": material_zone.zone_id, "load_type": load_type},
        )
    if (
        work_zone.accepted_load_types is not None
        and load_type not in work_zone.accepted_load_types
    ):
        raise TaskGenerationError(
            "work zone rejects load type",
            error_code="TASK_E_001",
            reason="dropoff_zone_rejects_load_type",
            details={"zone_id": work_zone.zone_id, "load_type": load_type},
        )


def _planned_start_s(
    scenario: ScenarioConfig,
    rng: random.Random,
    task_type: str,
    task_index: int,
    crane: CraneConfig,
) -> Optional[float]:
    policy = scenario.tasks.queue_policy
    if task_index > 1:
        return None
    if policy.start_mode is QueueStartMode.SIMULTANEOUS:
        return 0.0
    if policy.start_mode is QueueStartMode.SCHEDULED:
        return float(_stable_int(scenario.seed, crane.crane_id, task_index) % 30)
    start = rng.uniform(policy.initial_start_jitter_s[0], policy.initial_start_jitter_s[1])
    if task_type == "stress_task":
        start = min(start, 3.0)
    return round(start, 3)


def _deadline_s(task_type: str, priority: str) -> float:
    base_by_type = {
        "easy_task": 220.0,
        "overlap_task": 180.0,
        "stress_task": 140.0,
    }
    multiplier_by_priority = {
        "low": 1.15,
        "medium": 1.0,
        "high": 0.85,
    }
    deadline = base_by_type[task_type] * multiplier_by_priority[priority]
    if task_type == "stress_task":
        deadline = min(deadline, base_by_type["stress_task"])
    return round(deadline, 3)


def _requires_overlap_only(scenario: ScenarioConfig) -> bool:
    distribution = {
        key.value if hasattr(key, "value") else str(key): value
        for key, value in scenario.tasks.task_type_distribution.items()
    }
    return distribution.get("easy_task", 0.0) == 0 and (
        distribution.get("overlap_task", 0.0) > 0
        or distribution.get("stress_task", 0.0) > 0
    )


def _task_type_weight(scenario: ScenarioConfig, task_type: str) -> float:
    for key, value in scenario.tasks.task_type_distribution.items():
        key_value = key.value if hasattr(key, "value") else str(key)
        if key_value == task_type:
            return value
    return 0.0


def _zone_center(zone: ZoneConfig) -> Optional[List[float]]:
    if zone.center is not None:
        return [zone.center[0], zone.center[1], _sample_z(zone, random.Random(0), zone.center[2])]
    if zone.points:
        x = sum(point[0] for point in zone.points) / len(zone.points)
        y = sum(point[1] for point in zone.points) / len(zone.points)
        z = zone.z_range_m[0] if zone.z_range_m else 0.0
        return [x, y, z]
    return None


def _point_reachable(crane: CraneConfig, point: Optional[Sequence[float]]) -> bool:
    if point is None:
        return False
    radius = horizontal_distance(crane.base, point)
    return (
        crane.trolley_r_min_m <= radius <= crane.trolley_r_max_m
        and crane.hook_h_min_world_m <= point[2] <= crane.hook_h_max_world_m
    )


def _stable_int(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return int(digest[:16], 16)
