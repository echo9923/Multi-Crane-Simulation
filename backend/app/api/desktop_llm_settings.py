from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from backend.app.core.secret_resolver import mask_api_key
from backend.app.schemas.enums import LLMProviderName

SECRET_STORE_RELATIVE_PATH = Path(".desktop") / "secrets" / "llm_providers.json"
REAL_DESKTOP_PROVIDERS = {
    LLMProviderName.DEEPSEEK,
    LLMProviderName.MINIMAX,
    LLMProviderName.SILICONFLOW,
}


@dataclass(frozen=True)
class ProviderPreset:
    provider: LLMProviderName
    display_name: str
    default_base_url: Optional[str]
    default_model: str
    api_key_env: Optional[str]


@dataclass(frozen=True)
class SavedProviderSecret:
    api_key: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class DesktopProviderSummary:
    provider: str
    display_name: str
    default_base_url: Optional[str]
    default_model: str
    api_key_env: Optional[str]
    has_saved_key: bool
    key_masked: Optional[str]
    updated_at: Optional[str]


@dataclass(frozen=True)
class ConnectivityResult:
    ok: bool
    provider: str
    base_url: str
    latency_ms: float
    status_code: Optional[int] = None
    model_count: Optional[int] = None
    sample_models: Optional[list[str]] = None
    message: Optional[str] = None


PROVIDER_PRESETS: dict[LLMProviderName, ProviderPreset] = {
    LLMProviderName.DEEPSEEK: ProviderPreset(
        provider=LLMProviderName.DEEPSEEK,
        display_name="DeepSeek",
        default_base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    LLMProviderName.MINIMAX: ProviderPreset(
        provider=LLMProviderName.MINIMAX,
        display_name="MiniMax",
        default_base_url="https://api.minimax.chat/v1",
        default_model="abab6.5s-chat",
        api_key_env="MINIMAX_API_KEY",
    ),
    LLMProviderName.SILICONFLOW: ProviderPreset(
        provider=LLMProviderName.SILICONFLOW,
        display_name="SiliconFlow",
        default_base_url="https://api.siliconflow.cn/v1",
        default_model="deepseek-ai/DeepSeek-V4-Flash",
        api_key_env="SILICONFLOW_API_KEY",
    ),
    LLMProviderName.MOCK: ProviderPreset(
        provider=LLMProviderName.MOCK,
        display_name="Mock",
        default_base_url=None,
        default_model="mock-production",
        api_key_env=None,
    ),
    LLMProviderName.REPLAY: ProviderPreset(
        provider=LLMProviderName.REPLAY,
        display_name="Replay",
        default_base_url=None,
        default_model="replay",
        api_key_env=None,
    ),
}


class DesktopLLMSettingsError(RuntimeError):
    pass


class UrllibModelsHTTPClient:
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, Any]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, _loads_json_response(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _loads_json_response(exc.read())


def list_provider_summaries(project_root: Path | str) -> list[DesktopProviderSummary]:
    store = _read_store(project_root)
    return [_summary_for_preset(preset, store) for preset in PROVIDER_PRESETS.values()]


def save_provider_secret(
    project_root: Path | str,
    *,
    provider: LLMProviderName,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> DesktopProviderSummary:
    _require_real_provider(provider)
    cleaned_key = api_key.strip()
    if not cleaned_key:
        raise DesktopLLMSettingsError("api_key must be non-empty")
    store = _read_store(project_root)
    store[provider.value] = {
        "api_key": cleaned_key,
        "base_url": _clean_optional(base_url),
        "model": _clean_optional(model),
        "updated_at": _utc_now(),
    }
    _write_store(project_root, store)
    return _summary_for_preset(PROVIDER_PRESETS[provider], store)


def delete_provider_secret(
    project_root: Path | str,
    *,
    provider: LLMProviderName,
) -> DesktopProviderSummary:
    _require_real_provider(provider)
    store = _read_store(project_root)
    store.pop(provider.value, None)
    _write_store(project_root, store)
    return _summary_for_preset(PROVIDER_PRESETS[provider], store)


def load_saved_provider_secret(
    project_root: Path | str,
    *,
    provider: LLMProviderName,
) -> Optional[SavedProviderSecret]:
    payload = _read_store(project_root).get(provider.value)
    if not isinstance(payload, Mapping):
        return None
    api_key = payload.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        return None
    return SavedProviderSecret(
        api_key=api_key,
        base_url=_string_or_none(payload.get("base_url")),
        model=_string_or_none(payload.get("model")),
        updated_at=_string_or_none(payload.get("updated_at")),
    )


def resolve_local_api_key(
    project_root: Path | str | None,
    *,
    provider: LLMProviderName,
) -> Optional[str]:
    if project_root is None:
        return None
    secret = load_saved_provider_secret(project_root, provider=provider)
    return secret.api_key if secret is not None else None


def test_provider_connectivity(
    project_root: Path | str,
    *,
    provider: LLMProviderName,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    http_client: Optional[Any] = None,
    timeout_s: float = 10.0,
) -> ConnectivityResult:
    _require_real_provider(provider)
    preset = PROVIDER_PRESETS[provider]
    saved = load_saved_provider_secret(project_root, provider=provider)
    key = _clean_optional(api_key)
    if key is None and saved is not None:
        key = saved.api_key
    env_mapping = os.environ if env is None else env
    if key is None and preset.api_key_env:
        key = _clean_optional(env_mapping.get(preset.api_key_env))
    resolved_base_url = (
        _clean_optional(base_url)
        or (saved.base_url if saved is not None else None)
        or preset.default_base_url
    )
    if not resolved_base_url:
        raise DesktopLLMSettingsError("provider has no base URL")
    if key is None:
        return ConnectivityResult(
            ok=False,
            provider=provider.value,
            base_url=resolved_base_url,
            latency_ms=0.0,
            status_code=None,
            message="missing API key",
        )

    started = time.perf_counter()
    client = http_client or UrllibModelsHTTPClient()
    try:
        status_code, payload = client.get(
            _models_url(resolved_base_url),
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_s,
        )
    except TimeoutError:
        return _connectivity_error(
            provider=provider,
            base_url=resolved_base_url,
            started=started,
            message="provider request timed out",
        )
    except OSError:
        return _connectivity_error(
            provider=provider,
            base_url=resolved_base_url,
            started=started,
            message="provider request failed",
        )

    latency_ms = _elapsed_ms(started)
    if status_code == 200:
        models = _extract_model_ids(payload)
        return ConnectivityResult(
            ok=True,
            provider=provider.value,
            base_url=resolved_base_url,
            latency_ms=latency_ms,
            status_code=status_code,
            model_count=len(models),
            sample_models=models[:5],
            message="connected",
        )
    return ConnectivityResult(
        ok=False,
        provider=provider.value,
        base_url=resolved_base_url,
        latency_ms=latency_ms,
        status_code=status_code,
        message=_status_message(status_code),
    )


def provider_from_path(value: str) -> LLMProviderName:
    try:
        return LLMProviderName(value)
    except ValueError as exc:
        raise DesktopLLMSettingsError(f"unsupported provider: {value}") from exc


def _summary_for_preset(
    preset: ProviderPreset,
    store: Mapping[str, Any],
) -> DesktopProviderSummary:
    saved = store.get(preset.provider.value)
    api_key = saved.get("api_key") if isinstance(saved, Mapping) else None
    return DesktopProviderSummary(
        provider=preset.provider.value,
        display_name=preset.display_name,
        default_base_url=preset.default_base_url,
        default_model=preset.default_model,
        api_key_env=preset.api_key_env,
        has_saved_key=isinstance(api_key, str) and bool(api_key),
        key_masked=mask_api_key(api_key) if isinstance(api_key, str) and api_key else None,
        updated_at=_string_or_none(saved.get("updated_at")) if isinstance(saved, Mapping) else None,
    )


def _require_real_provider(provider: LLMProviderName) -> None:
    if provider not in REAL_DESKTOP_PROVIDERS:
        raise DesktopLLMSettingsError(f"provider {provider.value} does not use an API key")


def _read_store(project_root: Path | str) -> dict[str, Any]:
    path = _store_path(project_root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DesktopLLMSettingsError("desktop LLM secret store is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DesktopLLMSettingsError("desktop LLM secret store must be a JSON object")
    return payload


def _write_store(project_root: Path | str, payload: Mapping[str, Any]) -> None:
    path = _store_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _chmod_private(tmp, 0o600)
    tmp.replace(path)
    _chmod_private(path, 0o600)


def _store_path(project_root: Path | str) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root / SECRET_STORE_RELATIVE_PATH


def _chmod_private(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        pass


def _loads_json_response(data: bytes) -> Any:
    if not data:
        return {}
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {}


def _models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def _extract_model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    values = payload.get("data")
    if not isinstance(values, list):
        return []
    models: list[str] = []
    for item in values:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            models.append(item["id"])
    return models


def _status_message(status_code: int) -> str:
    if status_code in {401, 403}:
        return "authentication failed"
    if status_code == 404:
        return "models endpoint not found; check base URL"
    return f"provider returned HTTP {status_code}"


def _connectivity_error(
    *,
    provider: LLMProviderName,
    base_url: str,
    started: float,
    message: str,
) -> ConnectivityResult:
    return ConnectivityResult(
        ok=False,
        provider=provider.value,
        base_url=base_url,
        latency_ms=_elapsed_ms(started),
        status_code=None,
        message=message,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed_ms(started: float) -> float:
    return max((time.perf_counter() - started) * 1000.0, 0.0)


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _string_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


test_provider_connectivity.__test__ = False
