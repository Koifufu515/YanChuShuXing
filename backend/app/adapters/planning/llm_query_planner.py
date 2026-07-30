from __future__ import annotations

import json
import time
from typing import Any

from jsonschema import Draft202012Validator

from app.application.errors import InvalidProviderOutputError
from app.application.models import (
    LLMCallTelemetry,
    LLMRequest,
    LLMResponse,
    QueryPlanPerformance,
    QueryPlanPhaseTelemetry,
    QueryPlanResult,
    QueryPlanValidation,
)
from app.application.query_plan_normalization import normalize_query_plan
from app.application.query_plan_validation import validate_business_rules
from app.ports.llm_provider import LLMProvider


class LLMQueryPlanner:
    def __init__(
        self,
        provider: LLMProvider,
        prompt: str,
        schema: dict[str, Any],
        context: dict[str, Any],
        timeout_seconds: float,
        temperature: float = 0.0,
    ) -> None:
        self.provider = provider
        self.prompt = prompt
        self.schema = schema
        self.context = context
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.validator = Draft202012Validator(schema)

    def plan(self, question: str) -> QueryPlanResult:
        planning_started = time.perf_counter()
        prompt_started = time.perf_counter()
        initial_prompt = self._build_initial_prompt(question)
        initial_prompt_build_ms = self._elapsed_ms(prompt_started)
        response = self.provider.complete(
            LLMRequest(
                system_prompt=self.prompt,
                user_prompt=initial_prompt,
                temperature=self.temperature,
                timeout_seconds=self.timeout_seconds,
                response_format="json_object",
            )
        )

        parse_started = time.perf_counter()
        plan = self._parse_model_json(response.text)
        initial_parse_ms = self._elapsed_ms(parse_started)
        (
            initial_validation,
            initial_validation_ms,
            initial_schema_validation_ms,
            initial_business_validation_ms,
        ) = self._validate_timed(plan, question)
        initial_telemetry = QueryPlanPhaseTelemetry(
            prompt_build_ms=initial_prompt_build_ms,
            llm=self._response_telemetry(response),
            parse_ms=initial_parse_ms,
            validation_ms=initial_validation_ms,
            schema_validation_ms=initial_schema_validation_ms,
            business_validation_ms=initial_business_validation_ms,
        )
        final_validation = initial_validation
        repair_attempted = False
        total_latency_ms = response.latency_ms
        repair_telemetry = None

        if not initial_validation.success:
            repair_attempted = True
            repair_prompt_started = time.perf_counter()
            repair_prompt = self._build_repair_prompt(
                question=question,
                plan=plan,
                validation=initial_validation,
            )
            repair_prompt_build_ms = self._elapsed_ms(repair_prompt_started)
            repair_response = self.provider.complete(
                LLMRequest(
                    system_prompt=self.prompt,
                    user_prompt=repair_prompt,
                    temperature=self.temperature,
                    timeout_seconds=self.timeout_seconds,
                    response_format="json_object",
                )
            )
            total_latency_ms += repair_response.latency_ms

            repair_parse_started = time.perf_counter()
            try:
                repaired_plan = self._parse_model_json(repair_response.text)
            except InvalidProviderOutputError:
                repaired_plan = plan
            repair_parse_ms = self._elapsed_ms(repair_parse_started)

            (
                final_validation,
                repair_validation_ms,
                repair_schema_validation_ms,
                repair_business_validation_ms,
            ) = self._validate_timed(repaired_plan, question)
            repair_telemetry = QueryPlanPhaseTelemetry(
                prompt_build_ms=repair_prompt_build_ms,
                llm=self._response_telemetry(repair_response),
                parse_ms=repair_parse_ms,
                validation_ms=repair_validation_ms,
                schema_validation_ms=repair_schema_validation_ms,
                business_validation_ms=repair_business_validation_ms,
            )

        total_planning_ms = self._elapsed_ms(planning_started)
        measured_ms = self._phase_measured_ms(initial_telemetry)
        if repair_telemetry is not None:
            measured_ms += self._phase_measured_ms(repair_telemetry)
        performance = QueryPlanPerformance(
            initial=initial_telemetry,
            repair=repair_telemetry,
            total_planning_ms=total_planning_ms,
            unattributed_ms=round(max(0.0, total_planning_ms - measured_ms), 3),
        )

        return QueryPlanResult(
            success=final_validation.success,
            question=question,
            model=response.model,
            latency_ms=total_latency_ms,
            repair_attempted=repair_attempted,
            initial_validation=initial_validation,
            schema_valid=final_validation.schema_valid,
            schema_errors=final_validation.schema_errors,
            business_valid=final_validation.business_valid,
            business_errors=final_validation.business_errors,
            query_plan=final_validation.query_plan,
            performance=performance,
        )

    def _validate(
        self,
        plan: dict[str, Any],
        question: str,
    ) -> QueryPlanValidation:
        validation, _, _, _ = self._validate_timed(plan, question)
        return validation

    def _validate_timed(
        self,
        plan: dict[str, Any],
        question: str,
    ) -> tuple[QueryPlanValidation, float, float, float]:
        validation_started = time.perf_counter()
        plan = normalize_query_plan(plan)
        schema_started = time.perf_counter()
        schema_errors = sorted(
            self.validator.iter_errors(plan),
            key=lambda item: list(item.path),
        )
        schema_error_payload = [
            {
                "path": ".".join(str(part) for part in error.path) or "$",
                "message": error.message,
            }
            for error in schema_errors
        ]
        schema_ms = self._elapsed_ms(schema_started)
        business_started = time.perf_counter()
        business_errors = validate_business_rules(plan, self.context, question)
        business_ms = self._elapsed_ms(business_started)
        validation = QueryPlanValidation(
            schema_valid=not schema_errors,
            schema_errors=schema_error_payload,
            business_valid=not business_errors,
            business_errors=business_errors,
            query_plan=plan,
        )
        return (
            validation,
            self._elapsed_ms(validation_started),
            schema_ms,
            business_ms,
        )

    @staticmethod
    def _response_telemetry(response: LLMResponse) -> LLMCallTelemetry:
        telemetry = response.telemetry
        if telemetry.latency_ms == response.latency_ms:
            return telemetry
        return LLMCallTelemetry(
            latency_ms=response.latency_ms,
            request_body_bytes=telemetry.request_body_bytes,
            response_body_bytes=telemetry.response_body_bytes,
            usage=telemetry.usage,
        )

    @staticmethod
    def _phase_measured_ms(phase: QueryPlanPhaseTelemetry) -> float:
        return (
            phase.prompt_build_ms
            + phase.llm.latency_ms
            + phase.parse_ms
            + phase.validation_ms
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    def _build_initial_prompt(self, question: str) -> str:
        return "\n\n".join(
            [
                f"用户原始问题：\n{question}",
                "正式语义上下文：\n"
                + json.dumps(
                    self.context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "必须满足的JSON Schema：\n"
                + json.dumps(
                    self.schema,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ]
        )

    def _build_repair_prompt(
        self,
        question: str,
        plan: dict[str, Any],
        validation: QueryPlanValidation,
    ) -> str:
        return "\n\n".join(
            [
                f"用户原始问题：\n{question}",
                "正式语义上下文：\n"
                + json.dumps(
                    self.context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "必须满足的JSON Schema：\n"
                + json.dumps(
                    self.schema,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "上一版查询计划：\n"
                + json.dumps(
                    plan,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "上一版Schema错误：\n"
                + json.dumps(
                    validation.schema_errors,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "上一版业务错误：\n"
                + json.dumps(
                    validation.business_errors,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "请只返回修正后的完整JSON对象，不得解释，不得遗漏任何顶层字段。",
            ]
        )

    @staticmethod
    def _parse_model_json(text: str) -> dict[str, Any]:
        if not text or "```" in text:
            raise InvalidProviderOutputError(
                "DeepSeek输出不是严格JSON，或包含Markdown代码围栏。"
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidProviderOutputError(
                "DeepSeek输出不是合法JSON。"
            ) from exc
        if not isinstance(payload, dict):
            raise InvalidProviderOutputError(
                "DeepSeek输出顶层必须是JSON对象。"
            )
        return payload
