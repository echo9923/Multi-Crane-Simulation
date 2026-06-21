from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.app.schemas.config import LLMConfig
from backend.app.schemas.enums import LLMProviderName
from backend.app.schemas.resolved_config import PersistedProviderSummary


REAL_PROVIDERS = {
    LLMProviderName.DEEPSEEK,
    LLMProviderName.MINIMAX,
    LLMProviderName.SILICONFLOW,
}
FORBIDDEN_PERSISTED_SECRET_FIELDS = {
    "api_key",
    "resolved_full_api_key",
    "raw_api_key",
    "secret",
    "token",
    "authorization",
}


class SecretGovernanceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: Optional[str] = None,
        key_source: Optional[str] = None,
        missing_env: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> None:
        self.provider = provider
        self.key_source = key_source
        self.missing_env = missing_env
        self.hint = hint
        super().__init__(message)


@dataclass(frozen=True)
class ProviderRuntimeSecret:
    full_api_key: Optional[str]


@dataclass(frozen=True)
class ProviderSecretResolution:
    runtime_secret: ProviderRuntimeSecret
    persisted_summary: PersistedProviderSummary


def resolve_provider_secrets(
    llm_config: LLMConfig,
    *,
    env: Optional[dict] = None,
    local_api_key: Optional[str] = None,
) -> ProviderSecretResolution:
    provider = llm_config.provider
    inline_key = (
        llm_config.api_key.get_secret_value() if llm_config.api_key is not None else None
    )
    if inline_key:
        raise SecretGovernanceError(
            (
                f"provider {provider.value} cannot use an inline api_key at runtime. "
                "请在 API Key 页面输入并保存本机 API Key。"
            ),
            provider=provider.value,
            key_source="inline",
            missing_env=None,
            hint="Remove api_key from YAML and save a local desktop API Key.",
        )

    if local_api_key:
        key_source = "local_settings"
        full_api_key = local_api_key
        key_env_name = None
    else:
        key_source = "none"
        full_api_key = None
        key_env_name = None

    if llm_config.enabled and provider in REAL_PROVIDERS and not full_api_key:
        raise SecretGovernanceError(
            (
                f"provider {provider.value} requires an API key before startup. "
                "当前 provider 未找到 API Key，请回到配置页填写本机 API Key 并点击保存 Key。"
            ),
            provider=provider.value,
            key_source=key_source,
            missing_env=None,
            hint="Save a local desktop API Key for this provider before startup.",
        )

    summary = PersistedProviderSummary(
        provider=provider.value,
        model=llm_config.model,
        base_url=llm_config.base_url,
        temperature=llm_config.temperature,
        timeout_s=llm_config.timeout_s,
        max_retries=llm_config.max_retries,
        key_source=key_source,
        key_env_name=key_env_name,
        key_masked=mask_api_key(full_api_key) if full_api_key else None,
    )
    return ProviderSecretResolution(
        runtime_secret=ProviderRuntimeSecret(full_api_key=full_api_key),
        persisted_summary=summary,
    )


def mask_api_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def detect_inline_api_key_in_demo(raw_demo: dict) -> None:
    llm = raw_demo.get("experiment", {}).get("llm", {})
    api_key = llm.get("api_key")
    if isinstance(api_key, str) and _looks_like_real_key(api_key):
        raise SecretGovernanceError(
            "demo config contains a suspicious inline api_key; save the key locally instead",
            provider=llm.get("provider"),
            key_source="inline",
            hint="Remove api_key from YAML and save a local desktop API Key.",
        )


def assert_no_forbidden_secret_fields(payload: Any) -> None:
    offending_path = _find_forbidden_secret_field(payload)
    if offending_path is not None:
        raise SecretGovernanceError(
            f"forbidden persisted secret field: {offending_path}",
            hint="Persist only key_source, key_env_name and key_masked.",
        )


def _looks_like_real_key(value: str) -> bool:
    lowered = value.lower()
    return len(value) >= 16 and (
        lowered.startswith(("sk-", "mk-", "deepseek", "minimax"))
        or "secret" in lowered
        or "key" in lowered
    )


def _find_forbidden_secret_field(payload: Any, path: str = "") -> Optional[str]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            current_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_PERSISTED_SECRET_FIELDS:
                return current_path
            found = _find_forbidden_secret_field(value, current_path)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found = _find_forbidden_secret_field(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None
