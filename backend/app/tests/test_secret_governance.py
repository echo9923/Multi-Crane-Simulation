from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.config_hash import compute_resolved_config_hash
from backend.app.core.config_loader import load_demo_config
from backend.app.core.config_resolver import resolve_config
from backend.app.core.run_workspace import create_run_workspace
from backend.app.core.secret_resolver import (
    SecretGovernanceError,
    assert_no_forbidden_secret_fields,
    detect_inline_api_key_in_demo,
    mask_api_key,
    resolve_provider_secrets,
)
from backend.app.schemas.config import ExperimentConfig
from backend.app.schemas.enums import LLMProviderName
from backend.app.tests.test_config_schema import load_fixture


def _experiment_with(provider: str, *, api_key=None, api_key_env=None, enabled=True):
    raw = load_fixture("experiment_valid.yaml")
    raw["llm"]["enabled"] = enabled
    raw["llm"]["provider"] = provider
    raw["llm"]["api_key"] = api_key
    raw["llm"]["api_key_env"] = api_key_env
    raw["llm"]["model"] = f"{provider}-model"
    return ExperimentConfig.model_validate(raw)


def test_inline_api_key_wins_over_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-secret-123456")
    experiment = _experiment_with(
        "deepseek",
        api_key="sk-inline-secret-123456",
        api_key_env="DEEPSEEK_API_KEY",
    )

    resolved = resolve_provider_secrets(experiment.llm)

    assert resolved.runtime_secret.full_api_key == "sk-inline-secret-123456"
    assert resolved.persisted_summary.key_source == "inline"
    assert resolved.persisted_summary.key_env_name is None


def test_env_api_key_can_be_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "mk-env-secret-123456")
    experiment = _experiment_with(
        "minimax", api_key=None, api_key_env="MINIMAX_API_KEY"
    )

    resolved = resolve_provider_secrets(experiment.llm)

    assert resolved.runtime_secret.full_api_key == "mk-env-secret-123456"
    assert resolved.persisted_summary.key_source == "env"
    assert resolved.persisted_summary.key_env_name == "MINIMAX_API_KEY"
    assert resolved.persisted_summary.key_masked == "mk-e****3456"


def test_local_settings_key_can_be_resolved_when_env_is_missing() -> None:
    experiment = _experiment_with(
        "siliconflow",
        api_key=None,
        api_key_env="SILICONFLOW_API_KEY",
    )

    resolved = resolve_provider_secrets(
        experiment.llm,
        env={},
        local_api_key="sf-local-secret-123456",
    )

    assert resolved.runtime_secret.full_api_key == "sf-local-secret-123456"
    assert resolved.persisted_summary.key_source == "local_settings"
    assert resolved.persisted_summary.key_env_name is None
    assert resolved.persisted_summary.key_masked == "sf-l****3456"


@pytest.mark.parametrize("provider", [LLMProviderName.MOCK.value, LLMProviderName.REPLAY.value])
def test_mock_and_replay_do_not_require_key(provider: str) -> None:
    experiment = _experiment_with(provider, api_key=None, api_key_env=None)

    resolved = resolve_provider_secrets(experiment.llm)

    assert resolved.runtime_secret.full_api_key is None
    assert resolved.persisted_summary.key_source == "none"


@pytest.mark.parametrize(
    "provider",
    [
        LLMProviderName.DEEPSEEK.value,
        LLMProviderName.MINIMAX.value,
        LLMProviderName.SILICONFLOW.value,
    ],
)
def test_real_provider_missing_key_fails(provider: str) -> None:
    experiment = _experiment_with(provider, api_key=None, api_key_env=None)

    with pytest.raises(SecretGovernanceError) as exc_info:
        resolve_provider_secrets(experiment.llm)

    assert provider in str(exc_info.value)
    assert exc_info.value.provider == provider


def test_disabled_llm_does_not_require_real_provider_key() -> None:
    experiment = _experiment_with("deepseek", api_key=None, api_key_env=None, enabled=False)

    resolved = resolve_provider_secrets(experiment.llm)

    assert resolved.runtime_secret.full_api_key is None
    assert resolved.persisted_summary.key_source == "none"


def test_mask_api_key_never_returns_original_short_key() -> None:
    assert mask_api_key("short") == "****"
    assert mask_api_key("sk-inline-secret-123456") == "sk-i****3456"


def test_resolved_config_and_metadata_do_not_include_runtime_secret(tmp_path: Path) -> None:
    experiment = _experiment_with("deepseek", api_key="sk-inline-secret-123456")
    provider_resolution = resolve_provider_secrets(experiment.llm)
    resolved = resolve_config(
        load_fixture("scenario_valid.yaml"),
        experiment,
        provider_summary=provider_resolution.persisted_summary,
    )
    workspace = create_run_workspace(
        resolved,
        run_root=tmp_path,
        forbidden_secret_values=[provider_resolution.runtime_secret.full_api_key],
    )
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in workspace.created_files
    )

    assert provider_resolution.runtime_secret.full_api_key not in json.dumps(
        resolved.model_dump(mode="json")
    )
    assert provider_resolution.runtime_secret.full_api_key not in persisted
    assert resolved.provider.key_masked == "sk-i****3456"


def test_key_masked_does_not_affect_resolved_config_hash() -> None:
    experiment = _experiment_with("deepseek", api_key="sk-inline-secret-123456")
    provider_resolution = resolve_provider_secrets(experiment.llm)
    resolved = resolve_config(
        load_fixture("scenario_valid.yaml"),
        experiment,
        provider_summary=provider_resolution.persisted_summary,
    )
    changed = resolved.model_copy(
        update={
            "provider": resolved.provider.model_copy(update={"key_masked": "different"})
        }
    )

    assert compute_resolved_config_hash(changed) == resolved.resolved_config_hash


def test_demo_config_with_suspicious_inline_key_is_rejected() -> None:
    raw_demo = {"experiment": {"llm": {"api_key": "sk-real-looking-secret-123456"}}}

    with pytest.raises(SecretGovernanceError) as exc_info:
        detect_inline_api_key_in_demo(raw_demo)

    assert "demo" in str(exc_info.value).lower()
    assert "sk-real-looking-secret-123456" not in str(exc_info.value)


def test_demo_loader_rejects_suspicious_inline_key(tmp_path: Path) -> None:
    demo_path = tmp_path / "demo.yaml"
    demo_path.write_text(
        """
scenario: {}
experiment:
  llm:
    provider: deepseek
    api_key: sk-real-looking-secret-123456
""",
        encoding="utf-8",
    )

    with pytest.raises(SecretGovernanceError):
        load_demo_config(demo_path)


def test_forbidden_persisted_secret_field_names_are_rejected() -> None:
    with pytest.raises(SecretGovernanceError):
        assert_no_forbidden_secret_fields({"provider": {"raw_api_key": "secret"}})
