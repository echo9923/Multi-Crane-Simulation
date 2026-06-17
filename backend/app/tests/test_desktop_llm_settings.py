from __future__ import annotations

import json
from pathlib import Path

from backend.app.api.desktop_llm_settings import (
    SECRET_STORE_RELATIVE_PATH,
    delete_provider_secret,
    list_provider_summaries,
    resolve_local_api_key,
    save_provider_secret,
    test_provider_connectivity as run_provider_connectivity,
)
from backend.app.schemas.enums import LLMProviderName


class FakeModelsClient:
    def __init__(self, status_code: int | BaseException, payload=None) -> None:
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.calls: list[dict] = []

    def get(self, url, *, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        if isinstance(self.status_code, BaseException):
            raise self.status_code
        return self.status_code, self.payload


def test_save_delete_and_list_provider_secret_masks_key(tmp_path: Path) -> None:
    summary = save_provider_secret(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-secret-value-123456",
        base_url="https://api.siliconflow.cn/v1",
        model="deepseek-ai/DeepSeek-V4-Flash",
    )
    store_path = tmp_path / SECRET_STORE_RELATIVE_PATH
    persisted = store_path.read_text(encoding="utf-8")

    assert summary.provider == "siliconflow"
    assert summary.has_saved_key is True
    assert summary.key_masked == "sf-s****3456"
    assert "sf-secret-value-123456" in persisted
    assert resolve_local_api_key(tmp_path, provider=LLMProviderName.SILICONFLOW) == "sf-secret-value-123456"
    assert store_path.is_file()

    listed = list_provider_summaries(tmp_path)
    siliconflow = next(item for item in listed if item.provider == "siliconflow")
    assert siliconflow.key_masked == "sf-s****3456"
    assert "sf-secret-value-123456" not in json.dumps(
        [item.__dict__ for item in listed],
        sort_keys=True,
    )

    deleted = delete_provider_secret(tmp_path, provider=LLMProviderName.SILICONFLOW)

    assert deleted.has_saved_key is False
    assert deleted.key_masked is None
    assert resolve_local_api_key(tmp_path, provider=LLMProviderName.SILICONFLOW) is None


def test_provider_connectivity_uses_temp_key_and_reports_models(tmp_path: Path) -> None:
    client = FakeModelsClient(
        200,
        {"data": [{"id": "deepseek-ai/DeepSeek-V4-Flash"}, {"id": "deepseek-ai/DeepSeek-V3"}]},
    )

    result = run_provider_connectivity(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-temp-secret-123456",
        base_url="https://api.siliconflow.cn/v1/",
        http_client=client,
    )

    assert result.ok is True
    assert result.status_code == 200
    assert result.model_count == 2
    assert result.sample_models == ["deepseek-ai/DeepSeek-V4-Flash", "deepseek-ai/DeepSeek-V3"]
    assert client.calls[0]["url"] == "https://api.siliconflow.cn/v1/models"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer sf-temp-secret-123456"


def test_provider_connectivity_can_use_saved_key_without_leaking_it(tmp_path: Path) -> None:
    save_provider_secret(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-saved-secret-123456",
    )
    client = FakeModelsClient(401, {"error": "Invalid token"})

    result = run_provider_connectivity(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        http_client=client,
    )

    assert result.ok is False
    assert result.status_code == 401
    assert result.message == "authentication failed"
    assert "sf-saved-secret-123456" not in json.dumps(result.__dict__, sort_keys=True)


def test_provider_connectivity_reports_404_and_timeout(tmp_path: Path) -> None:
    not_found = run_provider_connectivity(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-temp-secret-123456",
        http_client=FakeModelsClient(404, {}),
    )
    timeout = run_provider_connectivity(
        tmp_path,
        provider=LLMProviderName.SILICONFLOW,
        api_key="sf-temp-secret-123456",
        http_client=FakeModelsClient(TimeoutError("slow")),
    )

    assert not_found.ok is False
    assert not_found.message == "models endpoint not found; check base URL"
    assert timeout.ok is False
    assert timeout.message == "provider request timed out"
