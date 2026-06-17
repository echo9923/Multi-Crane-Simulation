import json

import pytest
from pydantic import ValidationError

from backend.app.schemas.recorder import SimFrame, SimFrameWeather


def _minimal_sim_frame() -> SimFrame:
    return SimFrame(
        episode_id="E001",
        scenario_id="scenario-a",
        frame=0,
        time_s=0.0,
        episode_status="running",
        cranes=[],
        pairs=[],
        tasks=[],
        weather=SimFrameWeather(
            wind_speed_m_s=2.0,
            visibility="clear",
        ),
        events=[],
    )


def test_success_and_error_responses_use_uniform_shape() -> None:
    from backend.app.api.schemas import ApiErrorResponse, ApiResponse

    success = ApiResponse(data={"healthy": True})
    assert success.model_dump(mode="json") == {
        "code": 0,
        "data": {"healthy": True},
        "message": "ok",
    }

    error = ApiErrorResponse(
        code="M_E_EPISODE_NOT_FOUND",
        message="episode not found",
        details={"episode_id": "missing"},
    )
    assert error.model_dump(mode="json") == {
        "code": "M_E_EPISODE_NOT_FOUND",
        "data": None,
        "message": "episode not found",
        "details": {"episode_id": "missing"},
    }


def test_api_models_forbid_extra_fields_and_reject_invalid_pagination() -> None:
    from backend.app.api.schemas import ApiResponse, PaginationParams

    with pytest.raises(ValidationError):
        ApiResponse(data={}, unexpected=True)

    assert PaginationParams(limit=1, offset=0).limit == 1
    assert PaginationParams(limit=500, offset=0).limit == 500

    with pytest.raises(ValidationError):
        PaginationParams(limit=0)
    with pytest.raises(ValidationError):
        PaginationParams(limit=501)
    with pytest.raises(ValidationError):
        PaginationParams(offset=-1)


def test_episode_start_request_supports_config_path_and_inline_config() -> None:
    from backend.app.api.schemas import EpisodeStartRequest

    by_path = EpisodeStartRequest(config_path="configs/demo.yaml")
    assert by_path.config_path == "configs/demo.yaml"
    assert by_path.autostart is True

    inline = EpisodeStartRequest(
        scenario={"scenario_id": "scenario-a"},
        experiment={"experiment_id": "exp-a"},
        dataset={"dataset_id": "dataset-a"},
        run_mode="interactive_server",
        episode_id="E-custom",
    )
    assert inline.scenario == {"scenario_id": "scenario-a"}
    assert inline.run_mode == "interactive_server"
    assert inline.episode_id == "E-custom"

    with pytest.raises(ValidationError):
        EpisodeStartRequest(run_mode="realtime")


def test_episode_state_response_uses_recorder_sim_frame() -> None:
    from backend.app.api.schemas import EpisodeStateResponse

    frame = _minimal_sim_frame()
    state = EpisodeStateResponse(
        episode_id="E001",
        status="running",
        frame_index=frame.frame,
        time_s=frame.time_s,
        last_frame=frame,
    )

    assert isinstance(state.last_frame, SimFrame)
    dumped = state.model_dump(mode="json")
    assert dumped["last_frame"]["type"] == "sim_frame"
    assert dumped["last_frame"]["frame"] == 0


def test_dataset_models_and_error_codes_are_stable() -> None:
    from backend.app.api.schemas import (
        API_ERROR_CODES,
        DatasetListItem,
        DatasetListResponse,
        DatasetSummaryResponse,
    )

    assert API_ERROR_CODES
    assert all(code.startswith("M_E_") for code in API_ERROR_CODES)

    item = DatasetListItem(
        dataset_id="dataset-a",
        path="runs/datasets/dataset-a",
        num_episodes=3,
        summary_available=True,
    )
    response = DatasetListResponse(items=[item], total=1, limit=50, offset=0)
    assert response.items[0].dataset_id == "dataset-a"

    summary = DatasetSummaryResponse(
        dataset_id="dataset-a",
        summary={"num_episodes": 3},
    )
    assert summary.summary["num_episodes"] == 3

    with pytest.raises(ValidationError):
        DatasetListItem(
            dataset_id="dataset-a",
            path="runs/datasets/dataset-a",
            num_episodes=-1,
        )


def test_api_response_schema_does_not_define_secret_payload_fields() -> None:
    from backend.app.api import schemas

    schema_text = json.dumps(
        {
            name: model.model_json_schema()
            for name, model in vars(schemas).items()
            if isinstance(model, type)
            and hasattr(model, "model_json_schema")
            and getattr(model, "__module__", "") == schemas.__name__
            and name.endswith("Response")
        },
        sort_keys=True,
    ).lower()

    for forbidden in [
        "authorization",
        "provider_secret",
        "raw_api_key",
        "resolved_full_api_key",
    ]:
        assert forbidden not in schema_text
    assert '"api_key"' not in schema_text


def test_api_key_request_fields_are_limited_to_desktop_llm_settings() -> None:
    from backend.app.api import schemas

    request_models_with_api_key = {
        name
        for name, model in vars(schemas).items()
        if isinstance(model, type)
        and hasattr(model, "model_json_schema")
        and getattr(model, "__module__", "") == schemas.__name__
        and name.endswith("Request")
        and "api_key" in json.dumps(model.model_json_schema(), sort_keys=True).lower()
    }

    assert request_models_with_api_key == {
        "DesktopLLMConnectivityTestRequest",
        "DesktopLLMSecretSaveRequest",
    }
