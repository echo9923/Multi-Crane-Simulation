from __future__ import annotations

from typing import List, Optional

from backend.app.schemas.command import (
    CommandValidationError,
    LLMCallRecord,
    OperatorDecisionResult,
    OperatorSession,
    ParsedCommand,
    RawLLMResponse,
    build_neutral_stop_command as build_schema_neutral_stop_command,
)
from backend.app.schemas.config import LLMConfig
from backend.app.schemas.observation import Observation
from backend.app.sim.command_parser import (
    CommandParseError,
    parse_raw_llm_response,
    validation_errors_from_exception,
)
from backend.app.sim.llm_provider import (
    LLMProvider,
    ProviderAPIError,
    ProviderRequest,
    ProviderTimeoutError,
)
from backend.app.sim.prompt_builder import build_operator_messages


def decide_with_retry(
    observation: Observation,
    *,
    provider: LLMProvider,
    config: LLMConfig,
    session: OperatorSession,
) -> OperatorDecisionResult:
    validation_errors: List[CommandValidationError] = []
    call_records: List[LLMCallRecord] = []
    retry_errors: Optional[List[CommandValidationError]] = None
    last_response_id: Optional[str] = None
    max_attempts = 1 + config.max_retries

    for attempt_index in range(max_attempts):
        messages = build_operator_messages(
            observation,
            command_schema=ParsedCommand.model_json_schema(),
            command_duration_min_s=config.command_duration.min_s,
            command_duration_max_s=config.command_duration.max_s,
            command_duration_default_s=config.command_duration.default_s,
            retry_errors=retry_errors,
        )
        raw_response: Optional[RawLLMResponse] = None
        parsed_command: Optional[ParsedCommand] = None
        attempt_errors: List[CommandValidationError] = []
        latency_ms = None
        token_usage = None
        try:
            provider_result = provider.generate(
                ProviderRequest(
                    observation=observation,
                    messages=messages,
                    config=config,
                    runtime_secret=None,
                    attempt_index=attempt_index,
                )
            )
            raw_response = provider_result.raw_response
            latency_ms = provider_result.latency_ms
            token_usage = provider_result.token_usage
            if provider_result.replay_command is not None:
                parsed_command = provider_result.replay_command
            elif raw_response is not None:
                last_response_id = raw_response.response_id
                parsed_command = parse_raw_llm_response(
                    raw_response,
                    command_duration_min_s=config.command_duration.min_s,
                    command_duration_max_s=config.command_duration.max_s,
                )
        except (CommandParseError, ProviderTimeoutError, ProviderAPIError, Exception) as exc:
            attempt_errors = validation_errors_from_exception(exc)
            validation_errors.extend(attempt_errors)
            retry_errors = attempt_errors

        call_records.append(
            LLMCallRecord(
                call_id=f"call-{observation.observation_id}-{attempt_index}",
                observation=observation,
                messages=messages,
                raw_response=raw_response,
                parsed_command=parsed_command,
                validation_errors=attempt_errors,
                provider=provider.provider_name,
                model=config.model,
                latency_ms=latency_ms,
                token_usage=token_usage,
                attempt_index=attempt_index,
            )
        )

        if parsed_command is not None:
            session.consecutive_failures = 0
            session.decision_index += 1
            return OperatorDecisionResult(
                observation=observation,
                parsed_command=parsed_command,
                call_records=call_records,
                validation_errors=validation_errors,
                provider=provider.provider_name,
                model=config.model,
                fallback_applied=False,
            )

    fallback_reason = _fallback_reason(validation_errors)
    fallback_command = build_neutral_stop_command(
        observation,
        response_id=last_response_id,
        reason=fallback_reason,
        command_duration_s=config.command_duration.default_s,
    )
    session.consecutive_failures += 1
    session.decision_index += 1
    episode_failure_reason = (
        "llm_failed"
        if session.consecutive_failures >= config.max_consecutive_failures
        else None
    )
    return OperatorDecisionResult(
        observation=observation,
        parsed_command=fallback_command,
        call_records=call_records,
        validation_errors=validation_errors,
        provider=provider.provider_name,
        model=config.model,
        fallback_applied=True,
        episode_failure_reason=episode_failure_reason,
    )


def build_neutral_stop_command(
    observation: Observation,
    *,
    response_id: Optional[str],
    reason: str,
    command_duration_s: float,
) -> ParsedCommand:
    return build_schema_neutral_stop_command(
        observation_id=observation.observation_id,
        source_snapshot_id=observation.source_snapshot_id,
        operator_id=observation.operator_id,
        crane_id=observation.crane_id,
        time_s=observation.time_s,
        command_id=f"cmd-neutral-{observation.observation_id}",
        response_id=response_id,
        command_duration_s=command_duration_s,
        reason=reason,
    )


def _fallback_reason(errors: List[CommandValidationError]) -> str:
    if not errors:
        return "LLM output invalid/timeout; fallback to neutral_stop."
    first = errors[-1]
    if first.field_path:
        return f"{first.field_path}: {first.message}"
    return first.message
