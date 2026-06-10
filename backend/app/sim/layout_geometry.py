from __future__ import annotations

import math
from typing import Iterable, Sequence

from backend.app.schemas.config import BoundaryConfig, ZoneConfig


def horizontal_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def circle_intersection_area(radius_a: float, radius_b: float, distance_m: float) -> float:
    if distance_m >= radius_a + radius_b:
        return 0.0
    if distance_m <= abs(radius_a - radius_b):
        return math.pi * min(radius_a, radius_b) ** 2
    a2 = radius_a * radius_a
    b2 = radius_b * radius_b
    d2 = distance_m * distance_m
    alpha = math.acos((d2 + a2 - b2) / (2.0 * distance_m * radius_a))
    beta = math.acos((d2 + b2 - a2) / (2.0 * distance_m * radius_b))
    lens = 0.5 * math.sqrt(
        max(
            0.0,
            (-distance_m + radius_a + radius_b)
            * (distance_m + radius_a - radius_b)
            * (distance_m - radius_a + radius_b)
            * (distance_m + radius_a + radius_b),
        )
    )
    return a2 * alpha + b2 * beta - lens


def point_in_boundary(point: Sequence[float], boundary: BoundaryConfig) -> bool:
    return (
        boundary.x_min <= point[0] <= boundary.x_max
        and boundary.y_min <= point[1] <= boundary.y_max
        and boundary.z_min <= point[2] <= boundary.z_max
    )


def point_in_zone(point: Sequence[float], zone: ZoneConfig) -> bool:
    if zone.type == "box":
        return _point_in_box_zone(point, zone)
    if zone.type == "polygon":
        return _point_in_polygon_zone(point, zone)
    return False


def unsupported_zone_shapes(zones: Iterable[ZoneConfig]) -> list[str]:
    return [zone.zone_id for zone in zones if zone.type not in {"box", "polygon"}]


def _point_in_box_zone(point: Sequence[float], zone: ZoneConfig) -> bool:
    if zone.center is None or zone.size is None:
        return False
    x_ok = abs(point[0] - zone.center[0]) <= zone.size[0] / 2.0
    y_ok = abs(point[1] - zone.center[1]) <= zone.size[1] / 2.0
    if zone.z_range_m is not None:
        z_ok = zone.z_range_m[0] <= point[2] <= zone.z_range_m[1]
    else:
        z_ok = abs(point[2] - zone.center[2]) <= zone.size[2] / 2.0
    return x_ok and y_ok and z_ok


def _point_in_polygon_zone(point: Sequence[float], zone: ZoneConfig) -> bool:
    if not zone.points:
        return False
    if zone.z_range_m is not None and not (
        zone.z_range_m[0] <= point[2] <= zone.z_range_m[1]
    ):
        return False
    x, y = point[0], point[1]
    inside = False
    points = zone.points
    j = len(points) - 1
    for i, current in enumerate(points):
        previous = points[j]
        yi, yj = current[1], previous[1]
        xi, xj = current[0], previous[0]
        crosses = (yi > y) != (yj > y)
        if crosses:
            x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_at_y:
                inside = not inside
        j = i
    return inside
