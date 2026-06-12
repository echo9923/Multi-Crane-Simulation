from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Optional

import pytest

from backend.app.schemas.config import RiskConfig
from backend.app.schemas.scheduler import FORBIDDEN_SNAPSHOT_KEYS
from backend.app.schemas.state import CraneState
from backend.app.sim.offline_label import (
    OfflineLabelGenerator,
    OfflineTrajectoryFrame,
    build_offline_risk_report,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def _risk_config(**overrides) -> RiskConfig:
    payload = {
        "geometry_envelope": {
            "jib_radius_m": 0.5,
            "hook_radius_m": 0.5,
            "load_radius_m": 0.8,
        },
        "thresholds_m": {
            "low": 20.0,
            "medium": 12.0,
            "high": 8.0,
            "near_miss": 3.0,
        },
        "ttc_threshold_level": "high",
        "wind_safe_distance_factor": {
            "enabled": False,
            "extra_clearance_per_10m_s_wind_m": 0.0,
        },
    }
    payload.update(overrides)
    return RiskConfig.model_validate(payload)


def _state(
    crane_id: str,
    *,
    y_m: float,
    hook_y_m: Optional[float] = None,
) -> CraneState:
    hook_y = y_m if hook_y_m is None else hook_y_m
    return CraneState(
        crane_id=crane_id,
        theta_rad=0.0,
        theta_sin=0.0,
        theta_cos=1.0,
        trolley_r_m=5.0,
        hook_h_m=6.0,
        root_position=[0.0, y_m, 10.0],
        tip_position=[10.0, y_m, 10.0],
        hook_position=[5.0, hook_y, 6.0],
        cable_length_m=4.0,
    )


def _frame(frame: int, time_s: float, *states: CraneState) -> OfflineTrajectoryFrame:
    return OfflineTrajectoryFrame(
        episode_id="ep-acceptance",
        frame=frame,
        time_s=time_s,
        crane_states=list(states),
    )


def test_module_k_end_to_end_episode_generates_labels_and_report() -> None:
    risk_config = _risk_config(future_windows_s=[5.0, 10.0, 15.0])
    frames = [
        _frame(
            0,
            0.0,
            _state("C1", y_m=0.0),
            _state("C2", y_m=6.0),
            _state("C3", y_m=14.0),
        ),
        _frame(
            1,
            1.0,
            _state("C1", y_m=0.0),
            _state("C2", y_m=4.0),
            _state("C3", y_m=14.0),
        ),
        _frame(
            2,
            2.0,
            _state("C1", y_m=0.0),
            _state("C2", y_m=0.4),
            _state("C3", y_m=14.0),
        ),
    ]

    labels = OfflineLabelGenerator().generate(
        episode_id="ep-acceptance",
        scenario_id="scenario-acceptance",
        trajectory_frames=frames,
        crane_configs=[],
        risk_config=risk_config,
    )
    report = build_offline_risk_report(labels=labels)

    assert len(labels) == 9
    assert {label.pair_id for label in labels} == {"C1-C2", "C1-C3", "C2-C3"}
    c1_c2_first = next(label for label in labels if label.frame == 0 and label.pair_id == "C1-C2")
    assert c1_c2_first.collision_label_5s == 1
    assert c1_c2_first.risk_level_5s == "collision"
    assert "15s" in c1_c2_first.future_window_labels
    assert report.total_labels == len(labels)
    assert any(aggregate.group_by == "crane_pair" for aggregate in report.aggregates)


def test_module_k_labels_are_parquet_friendly_without_writing_files() -> None:
    risk_config = _risk_config()
    labels = OfflineLabelGenerator().generate(
        episode_id="ep-acceptance",
        trajectory_frames=[
            _frame(0, 0.0, _state("C1", y_m=0.0), _state("C2", y_m=5.0)),
        ],
        crane_configs=[],
        risk_config=risk_config,
    )

    row = labels[0].model_dump(mode="json")

    assert row["episode_id"] == "ep-acceptance"
    assert row["distance_min_raw_now_m"] >= 0
    assert row["future_window_labels"]["5s"]["used_future_truth"] is True
    json.dumps(row, ensure_ascii=False)


def test_module_k_static_imports_do_not_touch_online_or_prompt_modules() -> None:
    offline_imports = _imported_modules(REPO_ROOT / "backend/app/sim/offline_label.py")

    assert "backend.app.sim.prompt_builder" not in offline_imports
    assert "backend.app.sim.operator_orchestrator" not in offline_imports
    assert "backend.app.schemas.observation" not in offline_imports
    assert "backend.app.sim.risk" not in offline_imports

    risk_imports = _imported_modules(REPO_ROOT / "backend/app/sim/risk.py")

    assert "backend.app.sim.offline_label" not in risk_imports


def test_module_k_forbidden_fields_remain_blocked_from_scheduler_snapshot() -> None:
    assert "offline_label" in FORBIDDEN_SNAPSHOT_KEYS
    assert "offline_ttc" in FORBIDDEN_SNAPSHOT_KEYS
    assert "future_min_distance" in FORBIDDEN_SNAPSHOT_KEYS


def test_module_k_generator_does_not_write_parquet_or_jsonl() -> None:
    source = (REPO_ROOT / "backend/app/sim/offline_label.py").read_text(
        encoding="utf-8"
    )

    assert ".to_parquet" not in source
    assert "jsonlines" not in source
    assert "open(" not in source


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports
