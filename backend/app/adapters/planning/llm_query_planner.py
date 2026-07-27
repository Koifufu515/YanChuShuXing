from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from app.application.errors import InvalidProviderOutputError
from app.application.models import (
    LLMRequest,
    QueryPlanResult,
    QueryPlanValidation,
)
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
        response = self.provider.complete(
            LLMRequest(
                system_prompt=self.prompt,
                user_prompt=self._build_initial_prompt(question),
                temperature=self.temperature,
                timeout_seconds=self.timeout_seconds,
                response_format="json_object",
            )
        )

        plan = self._parse_model_json(response.text)
        initial_validation = self._validate(plan, question)
        final_validation = initial_validation
        repair_attempted = False
        total_latency_ms = response.latency_ms

        if not initial_validation.success:
            repair_attempted = True
            repair_response = self.provider.complete(
                LLMRequest(
                    system_prompt=self.prompt,
                    user_prompt=self._build_repair_prompt(
                        question=question,
                        plan=plan,
                        validation=initial_validation,
                    ),
                    temperature=self.temperature,
                    timeout_seconds=self.timeout_seconds,
                    response_format="json_object",
                )
            )
            total_latency_ms += repair_response.latency_ms

            try:
                repaired_plan = self._parse_model_json(repair_response.text)
            except InvalidProviderOutputError:
                repaired_plan = plan

            final_validation = self._validate(repaired_plan, question)

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
        )

    def _validate(
        self,
        plan: dict[str, Any],
        question: str,
    ) -> QueryPlanValidation:
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
        business_errors = validate_business_rules(
            plan,
            self.context,
            question,
        )

        return QueryPlanValidation(
            schema_valid=not schema_errors,
            schema_errors=schema_error_payload,
            business_valid=not business_errors,
            business_errors=business_errors,
            query_plan=plan,
        )

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
