from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.app.core.config_resolver import resolve_config
from backend.app.schemas.config import ScenarioConfig
from backend.app.tests.test_config_schema import load_fixture


def _resolved_from_raw(scenario_raw: dict | None = None):
    return resolve_config(
        scenario_raw or load_fixture("scenario_valid.yaml"),
        load_fixture("experiment_valid.yaml"),
    )


def test_resolved_config_persists_module_d_defaults() -> None:
    resolved = _resolved_from_raw()
    state_machine = resolved.tasks.generation["state_machine"]
    recovery = resolved.tasks.generation["recovery"]

    assert state_machine["attach_speed_threshold"] == {
        "slew_deg_s": 0.3,
        "trolley_m_s": 0.08,
        "hoist_m_s": 0.05,
    }
    assert state_machine["release_speed_threshold"] == {
        "slew_deg_s": 0.3,
        "trolley_m_s": 0.08,
        "hoist_m_s": 0.05,
    }
    assert state_machine["no_progress_xy_epsilon_m"] == 0.25
    assert recovery == {
        "enabled": True,
        "policy": "attempt_safe_release",
        "emergency_drop_zones": [],
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["tasks"]["state_machine"].setdefault(
            "attach_speed_threshold",
            {"slew_deg_s": 0.3, "trolley_m_s": 0.08, "hoist_m_s": 0.05},
        ).__setitem__(
            "slew_deg_s",
            0.4,
        ),
        lambda raw: raw["tasks"].__setitem__(
            "recovery",
            {
                "enabled": True,
                "policy": "terminate_episode",
                "emergency_drop_zones": [],
            },
        ),
        lambda raw: raw["tasks"]["state_machine"].__setitem__(
            "no_progress_xy_epsilon_m", 0.5
        ),
    ],
)
def test_task_runtime_contract_changes_affect_resolved_config_hash(mutate) -> None:
    baseline = _resolved_from_raw()
    changed_raw = load_fixture("scenario_valid.yaml")
    mutate(changed_raw)

    changed = _resolved_from_raw(changed_raw)

    assert changed.resolved_config_hash != baseline.resolved_config_hash


def test_recovery_release_cannot_enter_generation_distribution_schema() -> None:
    raw = load_fixture("scenario_valid.yaml")
    raw["tasks"]["task_type_distribution"] = {
        "easy_task": 0.5,
        "recovery_release": 0.5,
    }

    with pytest.raises(ValidationError):
        ScenarioConfig.model_validate(raw)
