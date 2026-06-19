from __future__ import annotations

import math
from random import Random
from typing import Any, Dict, List, Optional, Tuple

from backend.app.schemas.config import ManualCraneLayoutInput, ScenarioConfig
from backend.app.schemas.crane import CraneConfig, CraneModelLibrary, LayoutDiagnostics
from backend.app.schemas.enums import CoverageTarget, HeightStrategy, OverlapLevel, SlewMode
from backend.app.schemas.enums import LayoutMode
from backend.app.schemas.enums import TaskGenerationMode
from backend.app.schemas.errors import ConfigError
from backend.app.sim.layout import (
    LayoutResolutionError,
    build_crane_configs,
    build_layout_diagnostics,
    validate_manual_layout,
)
from backend.app.sim.layout_geometry import horizontal_distance
from backend.app.sim.layout_reachability import check_layout_reachability


class AutoLayoutError(Exception):
    def __init__(
        self,
        message: str,
        *,
        max_sampling_attempts: int,
        attempts: int,
        last_failure_reason: str,
        failure_counts_by_reason: Dict[str, int],
        layout_params: Dict[str, Any],
        seed: int,
    ) -> None:
        super().__init__(message)
        self.error_code = "LAY_E_001"
        self.category = "startup_error"
        self.field_path = "layout"
        self.details = {
            "max_sampling_attempts": max_sampling_attempts,
            "attempts": attempts,
            "last_failure_reason": last_failure_reason,
            "failure_counts_by_reason": failure_counts_by_reason,
            "layout_params": layout_params,
            "seed": seed,
        }


def auto_layout_error_to_config_error(
    error: AutoLayoutError,
    *,
    source_file: Optional[str] = None,
) -> ConfigError:
    return ConfigError(
        error_code=error.error_code,
        message=str(error),
        field_path=error.field_path,
        source_file=source_file,
        hint="Relax layout constraints or increase max_sampling_attempts.",
        details=error.details,
    )


def generate_auto_layout(
    scenario: ScenarioConfig,
    model_library: CraneModelLibrary,
    *,
    seed: int,
) -> Tuple[List[CraneConfig], LayoutDiagnostics]:
    rng = Random(seed)
    best: Optional[Tuple[float, List[CraneConfig], LayoutDiagnostics]] = None
    failure_counts: Dict[str, int] = {}
    last_failure = "no_candidate_generated"

    for attempt in range(1, scenario.layout.max_sampling_attempts + 1):
        try:
            candidate_inputs = _candidate_inputs(scenario, model_library, rng, attempt)
            candidate_scenario = scenario.model_copy(
                update={
                    "layout": scenario.layout.model_copy(
                        update={"mode": LayoutMode.MANUAL, "num_cranes": len(candidate_inputs)}
                    ),
                    "cranes": candidate_inputs,
                }
            )
            validate_manual_layout(candidate_scenario, model_library)
            crane_configs = build_crane_configs(
                candidate_inputs,
                model_library,
                scenario,
                source="auto",
            )
            diagnostics = _score_layout(crane_configs, scenario)
            reachability_tasks = scenario.tasks.model_copy(
                update={"generation_mode": TaskGenerationMode.MANUAL}
            )
            reachability = check_layout_reachability(
                [crane.model_dump(mode="json") for crane in crane_configs],
                [zone.model_dump(mode="json") for zone in scenario.site.material_zones],
                [zone.model_dump(mode="json") for zone in scenario.site.work_zones],
                {
                    key: value.model_dump(mode="json")
                    for key, value in scenario.load_types.items()
                },
                reachability_tasks.model_dump(mode="json"),
            )
            diagnostics = diagnostics.model_copy(
                update={
                    "warnings": diagnostics.warnings
                    + [
                        {
                            "reason": "layout_reachability_report",
                            "can_generate_tasks": reachability.can_generate_tasks,
                            "blocking_reasons": reachability.blocking_reasons,
                        }
                    ]
                }
            )
            if not reachability.can_generate_tasks:
                last_failure = "task_reachability_precheck_failed"
                failure_counts[last_failure] = failure_counts.get(last_failure, 0) + 1
                continue
            score = diagnostics.quality_score or 0.0
            if best is None or score > best[0]:
                best = (score, crane_configs, diagnostics)
            if _meets_targets(diagnostics, scenario):
                return crane_configs, diagnostics
            last_failure = "overlap_target_not_met"
            failure_counts[last_failure] = failure_counts.get(last_failure, 0) + 1
        except LayoutResolutionError as exc:
            last_failure = exc.reason
            failure_counts[last_failure] = failure_counts.get(last_failure, 0) + 1

    if best is not None:
        return best[1], best[2]

    raise AutoLayoutError(
        "auto layout failed within max_sampling_attempts",
        max_sampling_attempts=scenario.layout.max_sampling_attempts,
        attempts=scenario.layout.max_sampling_attempts,
        last_failure_reason=last_failure,
        failure_counts_by_reason=failure_counts or {last_failure: 1},
        layout_params=scenario.layout.model_dump(mode="json"),
        seed=seed,
    )


def _candidate_inputs(
    scenario: ScenarioConfig,
    model_library: CraneModelLibrary,
    rng: Random,
    attempt: int,
) -> List[ManualCraneLayoutInput]:
    boundary = scenario.site.boundary
    span_x = boundary.x_max - boundary.x_min
    span_y = boundary.y_max - boundary.y_min
    if min(span_x, span_y) < 20.0:
        raise LayoutResolutionError(
            "site boundary too small for auto layout",
            reason="base_out_of_boundary",
            field_path="site.boundary",
        )

    count = scenario.layout.num_cranes
    center_x, center_y = _layout_anchor(scenario)
    model_id = sorted(model_library)[0]
    model = model_library[model_id]
    placement_radius = _placement_radius(scenario, attempt)
    phase = rng.random() * math.tau + attempt * 0.013
    heights = _height_sequence(scenario, model, count)
    cranes: List[ManualCraneLayoutInput] = []
    for index in range(count):
        angle = phase + math.tau * index / count
        x = center_x + placement_radius * math.cos(angle)
        y = center_y + placement_radius * math.sin(angle)
        x = min(max(x, boundary.x_min + 5.0), boundary.x_max - 5.0)
        y = min(max(y, boundary.y_min + 5.0), boundary.y_max - 5.0)
        cranes.append(
            ManualCraneLayoutInput(
                crane_id=f"C{index + 1}",
                model_id=model_id,
                base=[x, y, boundary.z_min],
                mast_height_m=heights[index],
                theta_init_deg=(math.degrees(angle) + 180.0) % 360.0,
                slew={"mode": SlewMode.CONTINUOUS.value},
            )
        )
    return cranes


def _layout_anchor(scenario: ScenarioConfig) -> Tuple[float, float]:
    boundary = scenario.site.boundary
    anchors = [
        anchor
        for zone in [*scenario.site.material_zones, *scenario.site.work_zones]
        for anchor in [_zone_xy_anchor(zone)]
        if anchor is not None
    ]
    if not anchors:
        return (
            (boundary.x_min + boundary.x_max) / 2.0,
            (boundary.y_min + boundary.y_max) / 2.0,
        )
    x = sum(anchor[0] for anchor in anchors) / len(anchors)
    y = sum(anchor[1] for anchor in anchors) / len(anchors)
    return (
        min(max(x, boundary.x_min + 5.0), boundary.x_max - 5.0),
        min(max(y, boundary.y_min + 5.0), boundary.y_max - 5.0),
    )


def _zone_xy_anchor(zone) -> Optional[Tuple[float, float]]:
    if zone.center:
        return float(zone.center[0]), float(zone.center[1])
    if zone.points:
        return (
            sum(point[0] for point in zone.points) / len(zone.points),
            sum(point[1] for point in zone.points) / len(zone.points),
        )
    return None


def _placement_radius(scenario: ScenarioConfig, attempt: int) -> float:
    if scenario.layout.overlap_level is OverlapLevel.HIGH:
        base = 18.0
    elif scenario.layout.overlap_level is OverlapLevel.MEDIUM:
        base = 35.0
    else:
        base = 58.0
    if scenario.layout.coverage_target is CoverageTarget.WIDE_COVERAGE:
        base += 10.0
    if scenario.layout.coverage_target is CoverageTarget.DENSE_OVERLAP:
        base -= 8.0
    boundary = scenario.site.boundary
    max_radius = max(1.0, min(boundary.x_max - boundary.x_min, boundary.y_max - boundary.y_min) / 2.0 - 8.0)
    radii = [
        base,
        base * 0.75,
        base * 0.5,
        base * 0.35,
        base * 1.25,
    ]
    return min(max(1.0, radii[(attempt - 1) % len(radii)]), max_radius)


def _height_sequence(scenario: ScenarioConfig, model, count: int) -> List[float]:
    low, high = model.mast_height_range_m
    base = max(low, min(high, (low + high) / 2.0))
    if scenario.layout.height_strategy is HeightStrategy.STAGGERED:
        return [min(high, base + index * 6.0) for index in range(count)]
    if scenario.layout.height_strategy is HeightStrategy.SAME_LEVEL:
        return [base for _ in range(count)]
    values = []
    for index in range(count):
        delta = 0.0 if index % 2 == 0 else 7.0
        values.append(min(high, base + delta + (index // 2) * 2.0))
    return values


def _score_layout(cranes: List[CraneConfig], scenario: ScenarioConfig) -> LayoutDiagnostics:
    diagnostics = build_layout_diagnostics(
        cranes,
        mode="auto",
        warnings=[],
        quality_score=None,
    )
    pair_payloads = [pair.model_dump(mode="json") for pair in diagnostics.pair_diagnostics]
    avg_overlap = (
        sum(pair["overlap_ratio"] for pair in pair_payloads) / len(pair_payloads)
        if pair_payloads
        else 0.0
    )
    overlap_score = _overlap_target_score(avg_overlap, scenario.layout.overlap_level)
    coverage_score = _coverage_score(cranes, scenario)
    height_score = _height_score(pair_payloads, scenario.layout.height_strategy)
    boundary_score = _boundary_margin_score(cranes, scenario)
    quality = (
        overlap_score * 0.40
        + coverage_score * 0.30
        + height_score * 0.20
        + boundary_score * 0.10
    )
    return diagnostics.model_copy(
        update={
            "quality_score": quality,
            "overlap_target_score": overlap_score,
            "coverage_score": coverage_score,
            "height_strategy_score": height_score,
            "boundary_margin_score": boundary_score,
        }
    )


def _overlap_target_score(avg_overlap: float, level: OverlapLevel) -> float:
    ranges = {
        OverlapLevel.LOW: (0.05, 0.20),
        OverlapLevel.MEDIUM: (0.15, 0.45),
        OverlapLevel.HIGH: (0.35, 0.75),
    }
    low, high = ranges[level]
    if low <= avg_overlap <= high:
        return 1.0
    distance = min(abs(avg_overlap - low), abs(avg_overlap - high))
    return max(0.0, 1.0 - distance)


def _coverage_score(cranes: List[CraneConfig], scenario: ScenarioConfig) -> float:
    xs = [crane.base[0] for crane in cranes]
    ys = [crane.base[1] for crane in cranes]
    spread = (max(xs) - min(xs) + max(ys) - min(ys)) / 2.0 if cranes else 0.0
    site_span = min(
        scenario.site.boundary.x_max - scenario.site.boundary.x_min,
        scenario.site.boundary.y_max - scenario.site.boundary.y_min,
    )
    normalized = min(1.0, spread / max(site_span, 1.0))
    return normalized


def _height_score(pair_payloads: List[Dict[str, Any]], strategy: HeightStrategy) -> float:
    if not pair_payloads:
        return 1.0
    deltas = [
        pair["height_delta_m"]
        for pair in pair_payloads
        if pair["overlap_ratio"] > 0
    ]
    if not deltas:
        return 1.0
    if strategy is HeightStrategy.STAGGERED:
        return sum(1.0 for delta in deltas if delta >= 6.0) / len(deltas)
    if strategy is HeightStrategy.SAME_LEVEL:
        return sum(1.0 for delta in deltas if delta <= 3.0) / len(deltas)
    has_close = any(delta < 6.0 for delta in deltas)
    has_staggered = any(delta >= 6.0 for delta in deltas)
    return 1.0 if has_close and has_staggered else 0.5


def _boundary_margin_score(cranes: List[CraneConfig], scenario: ScenarioConfig) -> float:
    boundary = scenario.site.boundary
    margins = []
    for crane in cranes:
        x, y, _ = crane.base
        margins.append(
            min(
                x - boundary.x_min,
                boundary.x_max - x,
                y - boundary.y_min,
                boundary.y_max - y,
            )
        )
    return min(1.0, min(margins) / 20.0) if margins else 0.0


def _meets_targets(diagnostics: LayoutDiagnostics, scenario: ScenarioConfig) -> bool:
    return (
        (diagnostics.overlap_target_score or 0.0) >= 0.5
        and (diagnostics.height_strategy_score or 0.0) >= 0.5
    )
