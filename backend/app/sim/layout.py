from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.schemas.config import ManualCraneLayoutInput, ScenarioConfig
from backend.app.schemas.crane import (
    CraneConfig,
    CraneModelLibrary,
    LayoutDiagnostics,
    CranePairLayoutDiagnostic,
)
from backend.app.schemas.enums import LayoutMode, SlewMode
from backend.app.schemas.errors import ConfigError
from backend.app.sim.layout_geometry import (
    circle_intersection_area,
    horizontal_distance,
    point_in_boundary,
    point_in_zone,
    unsupported_zone_shapes,
)


MIN_BASE_DISTANCE_M = 8.0


class LayoutResolutionError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason: str,
        field_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.field_path = field_path
        self.details = details or {}


def layout_error_to_config_error(
    error: LayoutResolutionError,
    *,
    source_file: Optional[str] = None,
) -> ConfigError:
    details = dict(error.details)
    details["reason"] = error.reason
    return ConfigError(
        error_code="LAY_E_002",
        message=str(error),
        field_path=error.field_path,
        source_file=source_file,
        hint="Fix manual crane layout before startup.",
        details=details,
    )


@dataclass(frozen=True)
class ManualLayoutDiagnostics:
    warnings: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ManualLayoutValidationResult:
    cranes: List[ManualCraneLayoutInput]
    diagnostics: ManualLayoutDiagnostics


def validate_manual_layout(
    scenario: ScenarioConfig,
    model_library: CraneModelLibrary,
    *,
    min_base_distance_m: float = MIN_BASE_DISTANCE_M,
) -> ManualLayoutValidationResult:
    if scenario.layout.mode is not LayoutMode.MANUAL:
        raise LayoutResolutionError(
            "manual layout validation requires layout.mode=manual",
            reason="invalid_layout_mode",
            field_path="layout.mode",
        )
    cranes = list(scenario.cranes or [])
    if len(cranes) != scenario.layout.num_cranes:
        raise LayoutResolutionError(
            "manual crane count does not match layout.num_cranes",
            reason="manual_count_mismatch",
            field_path="cranes",
            details={
                "expected": scenario.layout.num_cranes,
                "actual": len(cranes),
            },
        )

    seen_ids: Set[str] = set()
    warnings = []
    unsupported = unsupported_zone_shapes(scenario.site.forbidden_zones)
    if unsupported:
        warnings.append(
            {
                "reason": "unsupported_zone_shape_for_base_check",
                "zone_ids": unsupported,
            }
        )

    for index, crane in enumerate(cranes):
        if crane.crane_id in seen_ids:
            raise LayoutResolutionError(
                f"duplicate crane_id: {crane.crane_id}",
                reason="duplicate_crane_id",
                field_path=f"cranes[{index}].crane_id",
                details={"crane_id": crane.crane_id},
            )
        seen_ids.add(crane.crane_id)

        model = model_library.get(crane.model_id)
        if model is None:
            raise LayoutResolutionError(
                f"unknown crane model_id: {crane.model_id}",
                reason="unknown_model_id",
                field_path=f"cranes[{index}].model_id",
                details={"model_id": crane.model_id},
            )

        if not point_in_boundary(crane.base, scenario.site.boundary):
            raise LayoutResolutionError(
                "crane base is outside site boundary",
                reason="base_out_of_boundary",
                field_path=f"cranes[{index}].base",
                details={"crane_id": crane.crane_id, "base": crane.base},
            )

        for zone in scenario.site.forbidden_zones:
            if point_in_zone(crane.base, zone):
                raise LayoutResolutionError(
                    "crane base is inside forbidden zone",
                    reason="base_inside_forbidden_zone",
                    field_path=f"cranes[{index}].base",
                    details={"crane_id": crane.crane_id, "zone_id": zone.zone_id},
                )

        min_height, max_height = model.mast_height_range_m
        if not (min_height <= crane.mast_height_m <= max_height):
            raise LayoutResolutionError(
                "mast height is outside model range",
                reason="mast_height_out_of_model_range",
                field_path=f"cranes[{index}].mast_height_m",
                details={
                    "crane_id": crane.crane_id,
                    "model_id": crane.model_id,
                    "mast_height_range_m": model.mast_height_range_m,
                    "mast_height_m": crane.mast_height_m,
                },
            )

        root_z = crane.base[2] + crane.mast_height_m
        if root_z > scenario.site.boundary.z_max:
            raise LayoutResolutionError(
                "crane root z is outside site boundary",
                reason="root_z_out_of_boundary",
                field_path=f"cranes[{index}].mast_height_m",
                details={"crane_id": crane.crane_id, "root_z": root_z},
            )

        if crane.slew.mode is SlewMode.LIMITED:
            raise LayoutResolutionError(
                "limited slew requires theta_limit_deg",
                reason="limited_slew_missing_theta_limit",
                field_path=f"cranes[{index}].slew",
                details={"crane_id": crane.crane_id},
            )
        if crane.slew.mode is not SlewMode.CONTINUOUS:
            raise LayoutResolutionError(
                "unsupported slew mode",
                reason="invalid_slew_mode",
                field_path=f"cranes[{index}].slew.mode",
                details={"crane_id": crane.crane_id},
            )

    for left_index, left in enumerate(cranes):
        for right in cranes[left_index + 1 :]:
            distance_m = horizontal_distance(left.base, right.base)
            if distance_m < min_base_distance_m:
                raise LayoutResolutionError(
                    "crane bases are too close",
                    reason="root_distance_too_small",
                    field_path="cranes",
                    details={
                        "crane_id_a": left.crane_id,
                        "crane_id_b": right.crane_id,
                        "distance_m": distance_m,
                        "min_base_distance_m": min_base_distance_m,
                    },
                )

    return ManualLayoutValidationResult(
        cranes=cranes,
        diagnostics=ManualLayoutDiagnostics(warnings=warnings),
    )


def create_crane_config(
    crane: ManualCraneLayoutInput,
    model_library: CraneModelLibrary,
    scenario: ScenarioConfig,
    *,
    source: str,
) -> CraneConfig:
    model = model_library[crane.model_id]
    root_z = crane.base[2] + crane.mast_height_m
    theta_init_rad = math.radians(crane.theta_init_deg)
    hook_h_min = max(
        scenario.site.boundary.z_min,
        root_z - model.cable_length_max_m,
    )
    hook_h_max = root_z - model.cable_length_min_m
    return CraneConfig(
        crane_id=crane.crane_id,
        model_id=crane.model_id,
        model=model,
        base=[float(value) for value in crane.base],
        root=[float(crane.base[0]), float(crane.base[1]), float(root_z)],
        mast_height_m=float(crane.mast_height_m),
        jib_length_m=model.jib_length_m,
        counter_jib_length_m=model.counter_jib_length_m,
        trolley_r_min_m=model.trolley_r_min_m,
        trolley_r_max_m=model.trolley_r_max_m,
        hook_h_min_world_m=float(hook_h_min),
        hook_h_max_world_m=float(hook_h_max),
        cable_length_min_m=model.cable_length_min_m,
        cable_length_max_m=model.cable_length_max_m,
        theta_init_rad=theta_init_rad,
        theta_init_deg=float(crane.theta_init_deg),
        theta_sin=math.sin(theta_init_rad),
        theta_cos=math.cos(theta_init_rad),
        slew_mode=crane.slew.mode.value,
        theta_limit_rad=None,
        source=source,  # type: ignore[arg-type]
    )


def build_crane_configs(
    cranes: List[ManualCraneLayoutInput],
    model_library: CraneModelLibrary,
    scenario: ScenarioConfig,
    *,
    source: str,
) -> List[CraneConfig]:
    return [
        create_crane_config(crane, model_library, scenario, source=source)
        for crane in cranes
    ]


def build_layout_diagnostics(
    crane_configs: List[CraneConfig],
    *,
    mode: str,
    warnings: Optional[List[Dict[str, Any]]] = None,
    quality_score: Optional[float] = None,
) -> LayoutDiagnostics:
    pairs: List[CranePairLayoutDiagnostic] = []
    for left_index, left in enumerate(crane_configs):
        for right in crane_configs[left_index + 1 :]:
            base_distance = horizontal_distance(left.base, right.base)
            root_distance = math.sqrt(
                (left.root[0] - right.root[0]) ** 2
                + (left.root[1] - right.root[1]) ** 2
                + (left.root[2] - right.root[2]) ** 2
            )
            intersection = circle_intersection_area(
                left.trolley_r_max_m,
                right.trolley_r_max_m,
                base_distance,
            )
            area_left = math.pi * left.trolley_r_max_m**2
            area_right = math.pi * right.trolley_r_max_m**2
            union = area_left + area_right - intersection
            min_area = min(area_left, area_right)
            overlap_ratio = 0.0 if min_area <= 0 else intersection / min_area
            pairs.append(
                CranePairLayoutDiagnostic(
                    crane_id_a=left.crane_id,
                    crane_id_b=right.crane_id,
                    root_distance_m=root_distance,
                    base_distance_m=base_distance,
                    height_delta_m=abs(left.root[2] - right.root[2]),
                    work_radius_overlap_area_m2=intersection,
                    work_radius_union_area_m2=union,
                    overlap_ratio=overlap_ratio,
                )
            )
    return LayoutDiagnostics(
        mode=mode,
        num_cranes=len(crane_configs),
        quality_score=quality_score,
        pair_diagnostics=pairs,
        warnings=warnings or [],
    )
