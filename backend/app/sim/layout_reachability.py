from __future__ import annotations

from typing import Any, Dict, List, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.crane import CraneConfig
from backend.app.sim.layout_geometry import horizontal_distance


class LayoutReachabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_generate_tasks: bool
    material_zone_reports: List[Dict[str, Any]]
    work_zone_reports: List[Dict[str, Any]]
    load_type_reports: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)


def check_layout_reachability(
    crane_configs: List[Union[Dict[str, Any], CraneConfig]],
    material_zones: List[Dict[str, Any]],
    work_zones: List[Dict[str, Any]],
    load_types: Dict[str, Dict[str, Any]],
    tasks: Dict[str, Any],
) -> LayoutReachabilityReport:
    cranes = [_normalize_crane(crane) for crane in crane_configs]
    blocking: List[str] = []
    warnings: List[Dict[str, Any]] = []

    material_reports = [
        _zone_report(zone, "material", cranes, load_types, tasks)
        for zone in material_zones
    ]
    work_reports = [
        _zone_report(zone, "work", cranes, load_types, tasks)
        for zone in work_zones
    ]

    for report in material_reports:
        if not report["reachable_by_crane_ids"]:
            _add_reason(blocking, "material_zone_unreachable")
        for load_type in report["supported_load_types"]:
            if load_type not in load_types:
                _add_reason(blocking, "unknown_load_type")

    for report in work_reports:
        if not report["reachable_by_crane_ids"]:
            _add_reason(blocking, "work_zone_unreachable")
        for load_type in report["supported_load_types"]:
            if load_type not in load_types:
                _add_reason(blocking, "unknown_load_type")

    material_load_types = set().union(
        *(set(report["supported_load_types"]) for report in material_reports)
    ) if material_reports else set()
    work_load_types = set().union(
        *(set(report["supported_load_types"]) for report in work_reports)
    ) if work_reports else set()
    common_load_types = material_load_types & work_load_types
    if material_load_types and work_load_types and not common_load_types:
        _add_reason(blocking, "no_material_work_load_type_intersection")

    reachable_radii_by_load_type = _reachable_radii_by_load_type(
        material_reports,
        work_reports,
    )
    load_type_reports = []
    for load_type in sorted(common_load_types or material_load_types or load_types):
        if load_type not in load_types:
            continue
        report = _load_type_report(
            load_type,
            load_types[load_type],
            cranes,
            reachable_radii_by_load_type.get(load_type, {}),
        )
        load_type_reports.append(report)
        if not report["reachable_by_crane_ids"]:
            _add_reason(blocking, "load_type_over_capacity")

    return LayoutReachabilityReport(
        can_generate_tasks=not blocking,
        material_zone_reports=material_reports,
        work_zone_reports=work_reports,
        load_type_reports=load_type_reports,
        warnings=warnings,
        blocking_reasons=blocking,
    )


def _normalize_crane(crane: Union[Dict[str, Any], CraneConfig]) -> Dict[str, Any]:
    if hasattr(crane, "model_dump"):
        return crane.model_dump(mode="json")  # type: ignore[return-value]
    return dict(crane)


def _zone_report(
    zone: Dict[str, Any],
    zone_type: str,
    cranes: List[Dict[str, Any]],
    load_types: Dict[str, Dict[str, Any]],
    tasks: Dict[str, Any],
) -> Dict[str, Any]:
    points = _representative_points(zone, zone_type, tasks)
    supported = zone.get("load_types") if zone_type == "material" else zone.get("accepted_load_types")
    supported = list(supported or load_types.keys())
    reachable_ids = []
    reachable_points_by_crane: Dict[str, List[Dict[str, Any]]] = {}
    for crane in cranes:
        reachable_points = [
            {
                "point": point,
                "radius_m": horizontal_distance(crane["base"], point),
            }
            for point in points
            if _point_reachable_by_crane(point, crane)
        ]
        if reachable_points:
            reachable_ids.append(crane["crane_id"])
            reachable_points_by_crane[crane["crane_id"]] = reachable_points
    return {
        "zone_id": zone["zone_id"],
        "zone_type": zone_type,
        "reachable_by_crane_ids": reachable_ids,
        "supported_load_types": supported,
        "representative_points_checked": points,
        "reachable_points_by_crane": reachable_points_by_crane,
    }


def _representative_points(
    zone: Dict[str, Any],
    zone_type: str,
    tasks: Dict[str, Any],
) -> List[List[float]]:
    z = _zone_z(zone, zone_type, tasks)
    if zone.get("type") == "box" and zone.get("center") and zone.get("size"):
        cx, cy, _ = zone["center"]
        sx, sy, _ = zone["size"]
        return [
            [cx, cy, z],
            [cx - sx / 2.0, cy - sy / 2.0, z],
            [cx + sx / 2.0, cy - sy / 2.0, z],
            [cx + sx / 2.0, cy + sy / 2.0, z],
            [cx - sx / 2.0, cy + sy / 2.0, z],
        ]
    if zone.get("type") == "polygon" and zone.get("points"):
        points = zone["points"]
        centroid = [
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
            z,
        ]
        return [centroid] + [[point[0], point[1], z] for point in points]
    if zone.get("center"):
        center = zone["center"]
        return [[center[0], center[1], z]]
    return [[0.0, 0.0, z]]


def _zone_z(zone: Dict[str, Any], zone_type: str, tasks: Dict[str, Any]) -> float:
    if zone.get("z_range_m"):
        low, high = zone["z_range_m"]
        return (low + high) / 2.0
    if zone_type == "material":
        return float(tasks["fallback_pickup_z_m"])
    low, high = tasks["fallback_dropoff_z_range_m"]
    return (low + high) / 2.0


def _point_reachable_by_crane(point: Sequence[float], crane: Dict[str, Any]) -> bool:
    distance = horizontal_distance(crane["base"], point)
    return (
        crane["trolley_r_min_m"] <= distance <= crane["trolley_r_max_m"]
        and crane["hook_h_min_world_m"] <= point[2] <= crane["hook_h_max_world_m"]
    )


def _load_type_report(
    load_type: str,
    load_config: Dict[str, Any],
    cranes: List[Dict[str, Any]],
    reachable_radii_by_crane: Dict[str, List[float]],
) -> Dict[str, Any]:
    max_weight = load_config["weight_range_t"][1]
    reachable_ids = []
    margins = []
    for crane in cranes:
        radii = reachable_radii_by_crane.get(crane["crane_id"], [])
        if not radii:
            continue
        capacity = max(
            _capacity_at_radius_from_payload(crane["model"], radius)
            for radius in radii
        )
        margin = capacity - max_weight
        margins.append(margin)
        if margin >= 0:
            reachable_ids.append(crane["crane_id"])
    return {
        "load_type": load_type,
        "max_weight_t": max_weight,
        "reachable_by_crane_ids": reachable_ids,
        "min_capacity_margin_t": min(margins) if margins else None,
    }


def _add_reason(blocking: List[str], reason: str) -> None:
    if reason not in blocking:
        blocking.append(reason)


def _reachable_radii_by_load_type(
    material_reports: List[Dict[str, Any]],
    work_reports: List[Dict[str, Any]],
) -> Dict[str, Dict[str, List[float]]]:
    result: Dict[str, Dict[str, List[float]]] = {}
    for material_report in material_reports:
        for work_report in work_reports:
            common_load_types = set(material_report["supported_load_types"]) & set(
                work_report["supported_load_types"]
            )
            for load_type in common_load_types:
                by_crane = result.setdefault(load_type, {})
                for crane_id in material_report["reachable_by_crane_ids"]:
                    radii = by_crane.setdefault(crane_id, [])
                    radii.extend(
                        point["radius_m"]
                        for point in material_report["reachable_points_by_crane"].get(
                            crane_id, []
                        )
                    )
                for crane_id in work_report["reachable_by_crane_ids"]:
                    radii = by_crane.setdefault(crane_id, [])
                    radii.extend(
                        point["radius_m"]
                        for point in work_report["reachable_points_by_crane"].get(
                            crane_id, []
                        )
                    )
    return result


def _capacity_at_radius_from_payload(model: Dict[str, Any], radius_m: float) -> float:
    if radius_m > model["jib_length_m"]:
        return 0.0
    if radius_m <= model["max_load_radius_m"]:
        chart_capacity = model["max_load_t"]
    else:
        left_r = model["max_load_radius_m"]
        right_r = model["jib_length_m"]
        t = (radius_m - left_r) / (right_r - left_r)
        chart_capacity = model["max_load_t"] + t * (
            model["tip_load_t"] - model["max_load_t"]
        )
    moment_capacity = model["rated_moment_t_m"] / max(
        radius_m,
        model["trolley_r_min_m"],
    )
    return max(0.0, min(chart_capacity, moment_capacity))
