from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core.secret_resolver import ProviderRuntimeSecret
from backend.app.schemas.command import (
    COMMAND_SCHEMA_VERSION,
    LLMMessage,
    ParsedCommand,
    RawLLMResponse,
    TokenUsage,
)
from backend.app.schemas.config import LLMConfig
from backend.app.schemas.enums import LLMProviderName, StructuredOutputMode
from backend.app.schemas.observation import Observation


class ProviderError(RuntimeError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderAPIError(ProviderError):
    pass


class ReplayCommandNotFoundError(ProviderError):
    pass


class ReplayCommandDuplicateError(ProviderError):
    pass


class ProviderBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProviderRequest(ProviderBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    observation: Observation
    messages: List[LLMMessage]
    config: LLMConfig
    runtime_secret: Optional[ProviderRuntimeSecret] = None
    attempt_index: int = Field(default=0, ge=0)


class ProviderResult(ProviderBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    raw_response: Optional[RawLLMResponse] = None
    replay_command: Optional[ParsedCommand] = None
    latency_ms: Optional[float] = Field(default=None, ge=0)
    token_usage: Optional[TokenUsage] = None

    @model_validator(mode="after")
    def validate_exactly_one_result(self) -> "ProviderResult":
        if (self.raw_response is None) == (self.replay_command is None):
            raise ValueError("exactly one of raw_response or replay_command is required")
        return self


class LLMProvider(Protocol):
    provider_name: LLMProviderName

    def generate(self, request: ProviderRequest) -> ProviderResult:
        ...


class MockProvider:
    provider_name = LLMProviderName.MOCK

    def generate(self, request: ProviderRequest) -> ProviderResult:
        started = time.perf_counter()
        payload = _mock_command_payload(request.observation)
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        raw_response = RawLLMResponse(
            response_id=_response_id(request, "mock"),
            provider=self.provider_name,
            model=request.config.model,
            observation_id=request.observation.observation_id,
            source_snapshot_id=request.observation.source_snapshot_id,
            operator_id=request.observation.operator_id,
            crane_id=request.observation.crane_id,
            time_s=request.observation.time_s,
            content=content,
            raw_payload={"provider": "mock"},
            latency_ms=_elapsed_ms(started),
            token_usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )
        return ProviderResult(
            raw_response=raw_response,
            latency_ms=raw_response.latency_ms,
            token_usage=raw_response.token_usage,
        )


class ReplayProvider:
    provider_name = LLMProviderName.REPLAY

    def __init__(self, *, replay_commands: Sequence[ParsedCommand]) -> None:
        self._replay_commands = list(replay_commands)

    def generate(self, request: ProviderRequest) -> ProviderResult:
        matches = [
            command
            for command in self._replay_commands
            if command.source_snapshot_id == request.observation.source_snapshot_id
            and command.crane_id == request.observation.crane_id
        ]
        if not matches:
            raise ReplayCommandNotFoundError(
                "no replay ParsedCommand for "
                f"snapshot={request.observation.source_snapshot_id} "
                f"crane={request.observation.crane_id}"
            )
        if len(matches) > 1:
            raise ReplayCommandDuplicateError(
                "multiple replay ParsedCommand records for "
                f"snapshot={request.observation.source_snapshot_id} "
                f"crane={request.observation.crane_id}"
            )
        return ProviderResult(replay_command=matches[0])


class DeepSeekProvider:
    provider_name = LLMProviderName.DEEPSEEK
    default_base_url = "https://api.deepseek.com/v1"

    def __init__(self, *, http_client: Optional[Any] = None) -> None:
        self._http_client = http_client or UrllibHTTPClient()

    def generate(self, request: ProviderRequest) -> ProviderResult:
        return _generate_chat_completion(
            provider_name=self.provider_name,
            default_base_url=self.default_base_url,
            http_client=self._http_client,
            request=request,
        )


class MiniMaxProvider:
    provider_name = LLMProviderName.MINIMAX
    default_base_url = "https://api.minimax.chat/v1"

    def __init__(self, *, http_client: Optional[Any] = None) -> None:
        self._http_client = http_client or UrllibHTTPClient()

    def generate(self, request: ProviderRequest) -> ProviderResult:
        return _generate_chat_completion(
            provider_name=self.provider_name,
            default_base_url=self.default_base_url,
            http_client=self._http_client,
            request=request,
        )


class SiliconFlowProvider:
    provider_name = LLMProviderName.SILICONFLOW
    default_base_url = "https://api.siliconflow.cn/v1"

    def __init__(self, *, http_client: Optional[Any] = None) -> None:
        self._http_client = http_client or UrllibHTTPClient()

    def generate(self, request: ProviderRequest) -> ProviderResult:
        return _generate_chat_completion(
            provider_name=self.provider_name,
            default_base_url=self.default_base_url,
            http_client=self._http_client,
            request=request,
        )


class UrllibHTTPResponse:
    def __init__(self, *, status_code: int, payload: Dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class UrllibHTTPClient:
    def post(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        json: Dict[str, Any],
        timeout: float,
    ) -> UrllibHTTPResponse:
        body = json_module_dumps(json).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json_module_loads(response.read().decode("utf-8"))
                return UrllibHTTPResponse(
                    status_code=response.status,
                    payload=payload,
                )
        except TimeoutError:
            raise
        except urllib.error.HTTPError as exc:
            try:
                payload = json_module_loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {"error": str(exc)}
            return UrllibHTTPResponse(status_code=exc.code, payload=payload)


def create_llm_provider(
    config: LLMConfig,
    *,
    replay_commands: Optional[Sequence[ParsedCommand]] = None,
) -> LLMProvider:
    if config.provider is LLMProviderName.MOCK:
        return MockProvider()
    if config.provider is LLMProviderName.REPLAY:
        return ReplayProvider(replay_commands=replay_commands or [])
    if config.provider is LLMProviderName.DEEPSEEK:
        return DeepSeekProvider()
    if config.provider is LLMProviderName.MINIMAX:
        return MiniMaxProvider()
    if config.provider is LLMProviderName.SILICONFLOW:
        return SiliconFlowProvider()
    raise ProviderAPIError(f"unsupported LLM provider: {config.provider}")


def _generate_chat_completion(
    *,
    provider_name: LLMProviderName,
    default_base_url: str,
    http_client: Any,
    request: ProviderRequest,
) -> ProviderResult:
    started = time.perf_counter()
    url = _chat_completions_url(request.config.base_url or default_base_url)
    headers = _headers(request.runtime_secret)
    payload = _chat_payload(request)
    try:
        response = http_client.post(
            url,
            headers=headers,
            json=payload,
            timeout=request.config.timeout_s,
        )
    except TimeoutError as exc:
        raise ProviderTimeoutError(f"{provider_name.value} provider timeout") from exc
    except OSError as exc:
        raise ProviderAPIError(f"{provider_name.value} provider request failed") from exc

    if response.status_code >= 400:
        raise ProviderAPIError(
            f"{provider_name.value} provider returned HTTP {response.status_code}"
        )

    response_payload = response.json()
    content = _extract_content(response_payload, provider_name=provider_name)
    token_usage = _token_usage(response_payload.get("usage"))
    latency_ms = _elapsed_ms(started)
    raw_response = RawLLMResponse(
        response_id=str(response_payload.get("id") or _response_id(request, provider_name.value)),
        provider=provider_name,
        model=request.config.model,
        observation_id=request.observation.observation_id,
        source_snapshot_id=request.observation.source_snapshot_id,
        operator_id=request.observation.operator_id,
        crane_id=request.observation.crane_id,
        time_s=request.observation.time_s,
        content=content,
        raw_payload={
            "id": response_payload.get("id"),
            "choices": response_payload.get("choices"),
            "usage": response_payload.get("usage"),
        },
        latency_ms=latency_ms,
        token_usage=token_usage,
    )
    return ProviderResult(
        raw_response=raw_response,
        latency_ms=latency_ms,
        token_usage=token_usage,
    )


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _headers(runtime_secret: Optional[ProviderRuntimeSecret]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if runtime_secret is not None and runtime_secret.full_api_key:
        headers["Authorization"] = f"Bearer {runtime_secret.full_api_key}"
    return headers


def _chat_payload(request: ProviderRequest) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": request.config.model,
        "messages": [
            message.model_dump(mode="json") for message in request.messages
        ],
        "temperature": request.config.temperature,
    }
    if request.config.structured_output.mode is StructuredOutputMode.JSON_SCHEMA:
        payload["response_format"] = {"type": "json_schema"}
    else:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _extract_content(
    response_payload: Dict[str, Any],
    *,
    provider_name: LLMProviderName,
) -> str:
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderAPIError(
            f"{provider_name.value} provider response missing message content"
        ) from exc
    if not isinstance(content, str):
        raise ProviderAPIError(
            f"{provider_name.value} provider response content must be a string"
        )
    return content


def _token_usage(payload: Any) -> Optional[TokenUsage]:
    if not isinstance(payload, dict):
        return None
    return TokenUsage(
        prompt_tokens=payload.get("prompt_tokens"),
        completion_tokens=payload.get("completion_tokens"),
        total_tokens=payload.get("total_tokens"),
    )


def _mock_command_payload(observation: Observation) -> Dict[str, Any]:
    if observation.task.has_active_task:
        left_joystick = {
            "slew": {"direction": "left", "gear": 1},
            "trolley": {"direction": "out", "gear": 1},
        }
        attention_target = "current_target"
        reason = "mock provider deterministic active task command"
    else:
        left_joystick = {
            "slew": {"direction": "neutral", "gear": 0},
            "trolley": {"direction": "neutral", "gear": 0},
        }
        attention_target = "idle"
        reason = "mock provider deterministic idle neutral command"

    return {
        "left_joystick": left_joystick,
        "right_joystick": {"hoist": {"direction": "neutral", "gear": 0}},
        "deadman_pressed": True,
        "emergency_stop": False,
        "horn": False,
        "command_duration_s": 1.0,
        "task_action": "none",
        "attention_target": attention_target,
        "confidence": 0.75,
        "reason": reason,
    }


def _response_id(request: ProviderRequest, provider_name: str) -> str:
    return (
        f"{provider_name}:{request.observation.source_snapshot_id}:"
        f"{request.observation.crane_id}:{request.attempt_index}"
    )


def _elapsed_ms(started: float) -> float:
    return max((time.perf_counter() - started) * 1000.0, 0.0)


def json_module_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def json_module_loads(payload: str) -> Dict[str, Any]:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise ProviderAPIError("provider response JSON must be an object")
    return parsed
