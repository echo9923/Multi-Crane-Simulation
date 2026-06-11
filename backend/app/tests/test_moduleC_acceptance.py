from __future__ import annotations

import ast
import math
from pathlib import Path

from backend.app.schemas.config import ScenarioConfig
from backend.app.schemas.control import ControlTarget
from backend.app.sim.crane_model import build_crane_model_library
from backend.app.sim.layout import build_crane_configs
from backend.app.sim.physics import (
    PHYSICS_SCHEMA_VERSION,
    initialize_world_state,
    step_world,
)
from backend.app.tests.test_config_schema import load_fixture


REPO_ROOT = Path(__file__).resolve().parents[3]


def _crane_configs(count: int = 4):
    raw = load_fixture("scenario_valid.yaml")
    raw["layout"]["mode"] = "manual"
    raw["layout"]["num_cranes"] = count
    raw["cranes"] = [
        {
            "crane_id": f"MC_{index + 1}",
            "model_id": "generic_flat_top_55m",
            "base": [-90.0 + index * 45.0, -75.0 + index * 30.0, 0.0],
            "mast_height_m": 45.0 + index * 2.0,
            "theta_init_deg": index * 15.0,
            "slew": {"mode": "continuous"},
        }
        for index in range(count)
    ]
    scenario = ScenarioConfig.model_validate(raw)
    model_library = build_crane_model_library(scenario.crane_models)
    return build_crane_configs(scenario.cranes, model_library, scenario, source="manual")


def _targets(crane_ids: list[str]) -> list[ControlTarget]:
    return [
        ControlTarget(
            crane_id=crane_id,
            target_slew_velocity_rad_s=0.01,
            target_trolley_velocity_m_s=0.2,
            target_hoist_velocity_m_s=-0.1,
        )
        for crane_id in crane_ids
    ]


def test_module_c_acceptance_steps_four_cranes_without_hardcoded_ids() -> None:
    cranes = _crane_configs(4)
    states = initialize_world_state(cranes)

    for _ in range(20):
        states = step_world(
            list(reversed(cranes)),
            states,
            _targets([crane.crane_id for crane in cranes]),
            dt=0.05,
        )

    assert {state.crane_id for state in states} == {"MC_1", "MC_2", "MC_3", "MC_4"}
    for state in states:
        assert state.schema_version == PHYSICS_SCHEMA_VERSION
        assert state.theta_sin == math.sin(state.theta_rad)
        assert state.theta_cos == math.cos(state.theta_rad)
        assert math.isfinite(state.theta_rad)
        assert math.isfinite(state.cable_length_m)
        assert len(state.tip_position) == 3
        assert len(state.hook_position) == 3


def test_module_c_public_implementation_does_not_import_adjacent_runtime_modules() -> None:
    banned_prefixes = (
        "backend.app.llm",
        "backend.app.risk",
        "backend.app.recorder",
        "backend.app.frontend",
        "backend.app.api",
        "backend.app.tasks",
    )
    module_paths = [
        REPO_ROOT / "backend/app/sim/physics.py",
        REPO_ROOT / "backend/app/schemas/state.py",
        REPO_ROOT / "backend/app/schemas/control.py",
    ]

    for path in module_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        assert not [
            module for module in imported if module.startswith(banned_prefixes)
        ], path


def test_module_c_task_document_contains_exit_contracts_without_placeholders() -> None:
    doc_path = REPO_ROOT / "docs/moduleC/README.md"
    text = doc_path.read_text(encoding="utf-8")

    for keyword in [
        "CraneState",
        "ControlTarget",
        "PHYS_E_001",
        "PHYS_E_002",
        "failed_invalid_state",
        "step_crane_state",
        "step_world",
        "hook_h_m",
        "cable_length_m",
        "theta_sin",
        "theta_cos",
    ]:
        assert keyword in text

    placeholders = [
        "TB" + "D",
        "TO" + "DO",
        "implement " + "later",
        "fill in " + "details",
        "<un" + "finished",
    ]
    assert not [placeholder for placeholder in placeholders if placeholder in text]
