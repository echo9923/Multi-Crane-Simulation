from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Dict, List, Optional, Sequence

from backend.app.schemas.command import (
    CommandValidationError,
    LLMCallRecord,
    LLMMessage,
    OperatorDecisionResult,
    OperatorSession,
    ParsedCommand,
    RawLLMResponse,
    build_neutral_stop_command as build_schema_neutral_stop_command,
)
from backend.app.schemas.config import LLMConfig
from backend.app.schemas.enums import LLMHistoryMode, OperatorProfile
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


class OperatorDecisionOrchestratorError(RuntimeError):
    pass


def decide_with_retry(
    observation: Observation,
    *,
    provider: LLMProvider,
    config: LLMConfig,
    session: OperatorSession,
    context_messages: Optional[List[LLMMessage]] = None,
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
        if context_messages:
            messages = [messages[0], *context_messages, *messages[1:]]
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


class OperatorDecisionOrchestrator:
    def __init__(
        self,
        *,
        config: LLMConfig,
        provider: LLMProvider,
        operator_profiles: Dict[str, OperatorProfile],
    ) -> None:
        self.config = config
        self.provider = provider
        self.operator_profiles = dict(operator_profiles)
        self._sessions: Dict[tuple[str, str], OperatorSession] = {}
        self._last_decision_time_by_crane: Dict[str, float] = {}

    def should_decide(
        self,
        *,
        crane_id: str,
        time_s: float,
        llm_decision_interval_s: float,
    ) -> bool:
        if llm_decision_interval_s <= 0:
            raise OperatorDecisionOrchestratorError(
                "llm_decision_interval_s must be positive"
            )
        last_decision_time = self._last_decision_time_by_crane.get(crane_id)
        if last_decision_time is None:
            return True
        return time_s - last_decision_time >= llm_decision_interval_s

    def decide(
        self,
        observations: Sequence[Observation],
        *,
        llm_decision_interval_s: float,
    ) -> List[OperatorDecisionResult]:
        self._validate_observation_batch(observations, llm_decision_interval_s)
        if not observations:
            return []
        decision_inputs = [
            (
                observation,
                self.get_session(observation.crane_id, observation.operator_id),
            )
            for observation in observations
        ]
        if len(observations) == 1 or self.config.scheduling.max_concurrent_requests == 1:
            return [
                self._decide_one_observation(
                    observation,
                    session=session,
                )
                for observation, session in decision_inputs
            ]

        max_workers = min(
            len(decision_inputs),
            self.config.scheduling.max_concurrent_requests,
        )
        results: List[Optional[OperatorDecisionResult]] = [None] * len(decision_inputs)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(
                    self._decide_one_observation,
                    observation,
                    session=session,
                ): index
                for index, (observation, session) in enumerate(decision_inputs)
            }
            for future, index in future_to_index.items():
                results[index] = future.result()
        ordered_results: List[OperatorDecisionResult] = []
        for result in results:
            if result is None:
                raise OperatorDecisionOrchestratorError("missing LLM decision result")
            ordered_results.append(result)
        return ordered_results

    def _decide_one_observation(
        self,
        observation: Observation,
        *,
        session: OperatorSession,
    ) -> OperatorDecisionResult:
        result = decide_with_retry(
            observation,
            provider=self.provider,
            config=self.config,
            session=session,
            context_messages=self._history_context_messages(observation, session),
        )
        session.history.extend(
            _summary_messages_from_result(
                result,
                limit=self.config.context.recent_decisions_full,
            )
        )
        if self.config.context.recent_decisions_full >= 0:
            session.history = session.history[-self.config.context.recent_decisions_full :]
        self._last_decision_time_by_crane[observation.crane_id] = observation.time_s
        return result

    def get_session(self, crane_id: str, operator_id: str) -> OperatorSession:
        profile = self.operator_profiles.get(crane_id)
        if profile is None:
            raise OperatorDecisionOrchestratorError(
                f"missing operator profile assignment for crane {crane_id}"
            )
        key = (crane_id, operator_id)
        if key not in self._sessions:
            self._sessions[key] = OperatorSession(
                operator_id=operator_id,
                crane_id=crane_id,
                profile=profile,
            )
        return self._sessions[key]

    def _validate_observation_batch(
        self,
        observations: Sequence[Observation],
        llm_decision_interval_s: float,
    ) -> None:
        if llm_decision_interval_s <= 0:
            raise OperatorDecisionOrchestratorError(
                "llm_decision_interval_s must be positive"
            )
        seen_cranes = set()
        snapshot_ids = {observation.source_snapshot_id for observation in observations}
        if len(snapshot_ids) > 1:
            raise OperatorDecisionOrchestratorError(
                "all observations in one decision batch must share source_snapshot_id"
            )
        for observation in observations:
            if observation.crane_id in seen_cranes:
                raise OperatorDecisionOrchestratorError(
                    f"duplicate observation for crane {observation.crane_id}"
                )
            seen_cranes.add(observation.crane_id)
            if observation.crane_id not in self.operator_profiles:
                raise OperatorDecisionOrchestratorError(
                    f"missing operator profile assignment for crane {observation.crane_id}"
                )

    def _history_context_messages(
        self,
        observation: Observation,
        session: OperatorSession,
    ) -> List[LLMMessage]:
        history_mode = self.config.context.history_mode
        if history_mode is LLMHistoryMode.NONE:
            return []
        payload: Dict[str, object] = {"history_mode": history_mode.value}
        if history_mode is LLMHistoryMode.SHORT:
            payload["recent_decisions"] = [
                decision.model_dump(mode="json")
                for decision in observation.memory.recent_decisions
            ]
            payload["session_history"] = [
                message.content for message in session.history
            ]
        elif history_mode is LLMHistoryMode.LONG:
            payload["task_history_summary"] = observation.memory.task_history_summary
            payload["recent_decisions"] = [
                decision.model_dump(mode="json")
                for decision in observation.memory.recent_decisions
            ]
            payload["event_summary"] = list(observation.memory.event_summary)
            payload["session_history"] = [
                message.content for message in session.history
            ]
        else:
            return []
        return [
            LLMMessage(
                role="user",
                content=(
                    "以下是仅包含已发生信息的 session_history，上下文不得包含未来真值：\n"
                    f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
                ),
            )
        ]


def _summary_messages_from_result(
    result: OperatorDecisionResult,
    *,
    limit: int,
) -> List[LLMMessage]:
    if limit == 0:
        return []
    command = result.parsed_command
    content = (
        f"time_s={command.time_s}; command_id={command.command_id}; "
        f"attention_target={command.attention_target}; "
        f"fallback={result.fallback_applied}"
    )
    return [LLMMessage(role="assistant", content=content)]
