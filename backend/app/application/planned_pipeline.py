from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from app.application.errors import ApplicationError
from app.application.models import (
    AuditEvent,
    ErrorDetail,
    QueryCommand,
    QueryMetadata,
    QueryOutcome,
    QueryPlanResult,
)
from app.ports.audit_logger import AuditLogger
from app.ports.query_plan_executor import QueryPlanExecutor
from app.ports.query_planner import QueryPlanner


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PendingClarification:
    original_question: str
    user_id: str
    conversation_id: str | None
    questions: list[dict[str, Any]]
    created_at: float


class PlannedQueryPipeline:
    """正式数据环境的查询规划、确定性执行与结构化返回链路。"""

    def __init__(
        self,
        query_planner: QueryPlanner,
        query_plan_executor: QueryPlanExecutor,
        audit_logger: AuditLogger,
        provider_name: str = "deepseek",
    ) -> None:
        self.query_planner = query_planner
        self.query_plan_executor = query_plan_executor
        self.audit_logger = audit_logger
        self.provider_name = provider_name
        self._clarifications: dict[str, _PendingClarification] = {}
        self._clarification_lock = RLock()
        self._clarification_ttl_seconds = 30 * 60

    def run(self, command: QueryCommand) -> QueryOutcome:
        logger.info(
            "planned_query_received request_id=%s question=%s",
            command.request_id,
            command.question,
        )
        self._record(command, "request_started")
        metadata: QueryMetadata | None = None
        try:
            planning_question = command.question
            if command.clarification_id is not None:
                try:
                    planning_question = self._consume_clarification(command)
                except ValueError as exc:
                    error = ErrorDetail(
                        code="INVALID_CONFIRMATION",
                        message=str(exc),
                        retryable=False,
                    )
                    self._record(command, "query_failed", error_code=error.code)
                    return QueryOutcome(
                        request_id=command.request_id,
                        question=command.question,
                        error=error,
                    )
            logger.info("llm_query_planner_call request_id=%s", command.request_id)
            plan_result = self.query_planner.plan(planning_question)
            metadata = self._metadata(plan_result)
            plan = plan_result.query_plan
            status = plan.get("status") if isinstance(plan, dict) else None
            logger.info(
                "query_plan_created request_id=%s model=%s latency_ms=%s status=%s semantics=%s",
                command.request_id,
                plan_result.model,
                plan_result.latency_ms,
                status.get("code") if isinstance(status, dict) else None,
                json.dumps(
                    {
                        "institutions": plan.get("institutions"),
                        "metrics": plan.get("metrics"),
                        "time": plan.get("time"),
                        "operations": [
                            item.get("operator_id")
                            for item in plan.get("operations", [])
                            if isinstance(item, dict)
                        ],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

            if not plan_result.success:
                error = ErrorDetail(
                    code="LLM_PROVIDER_ERROR",
                    message="查询计划在自动修复后仍未通过结构与业务校验。",
                    retryable=False,
                )
                metadata = self._metadata(plan_result, failure_reason="invalid_query_plan")
                self._record(command, "query_failed", error_code=error.code)
                return QueryOutcome(
                    request_id=command.request_id,
                    question=command.question,
                    error=error,
                    metadata=metadata,
                )

            status = plan_result.query_plan.get("status")
            status_code = status.get("code") if isinstance(status, dict) else None
            if status_code != "executable":
                error = self._status_error(status_code, status)
                metadata = self._metadata(
                    plan_result,
                    failure_reason=str(status_code or "invalid_status"),
                )
                self._record(command, "query_failed", error_code=error.code)
                clarification = None
                if status_code == "clarification_required":
                    clarification = self._issue_clarification(
                        command,
                        status if isinstance(status, dict) else {},
                    )
                return QueryOutcome(
                    request_id=command.request_id,
                    question=command.question,
                    error=error,
                    metadata=metadata,
                    confirmation=clarification,
                )

            execution = self.query_plan_executor.execute(plan_result.query_plan)
            logger.info(
                "query_plan_executed request_id=%s row_count=%s",
                command.request_id,
                len(execution.rows),
            )
            metadata = QueryMetadata(
                configured_mode="query_plan",
                executed_generator="query_planner",
                route="QueryPlan",
                provider=self.provider_name,
                model=plan_result.model,
                llm_latency_ms=plan_result.latency_ms,
                query_plan=plan_result.query_plan,
                execution_trace=execution.execution_trace,
                plan_repair_attempted=plan_result.repair_attempted,
            )
            self._record(command, "query_succeeded")
            return QueryOutcome(
                request_id=command.request_id,
                question=command.question,
                columns=execution.columns,
                rows=execution.rows,
                summary=execution.summary,
                warnings=execution.warnings,
                metadata=metadata,
            )
        except ApplicationError as exc:
            error = ErrorDetail(
                code=exc.code,
                message=exc.public_message,
                retryable=exc.retryable,
            )
            self._record(command, "query_failed", error_code=error.code)
            return QueryOutcome(
                request_id=command.request_id,
                question=command.question,
                error=error,
                metadata=metadata or exc.metadata,
            )
        except Exception:
            self._record(command, "query_failed", error_code="INTERNAL_ERROR")
            raise

    def _issue_clarification(
        self,
        command: QueryCommand,
        status: dict[str, Any],
    ) -> dict[str, Any]:
        questions = status.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError("查询规划器没有返回可执行的结构化澄清问题。")
        clarification_id = f"clar_{uuid4().hex}"
        pending = _PendingClarification(
            original_question=command.question,
            user_id=command.user_id,
            conversation_id=command.conversation_id,
            questions=questions,
            created_at=monotonic(),
        )
        with self._clarification_lock:
            self._discard_expired_clarifications()
            self._clarifications[clarification_id] = pending
        return {
            "status": "clarification_required",
            "clarification_id": clarification_id,
            "original_question": command.question,
            "questions": questions,
        }

    def _consume_clarification(self, command: QueryCommand) -> str:
        clarification_id = command.clarification_id or ""
        with self._clarification_lock:
            self._discard_expired_clarifications()
            pending = self._clarifications.get(clarification_id)
        if pending is None:
            raise ValueError("该确认请求已失效，请重新提交原问题。")
        if pending.user_id != command.user_id or pending.conversation_id != command.conversation_id:
            raise ValueError("该确认请求不属于当前用户或会话。")
        if command.question != pending.original_question:
            raise ValueError("确认请求中的原问题与待确认问题不一致。")
        answers = command.clarification_answers
        if not isinstance(answers, dict):
            raise ValueError("请完成后端要求的确认内容。")

        expected = {str(item.get("field")): item for item in pending.questions}
        if set(answers) - set(expected):
            raise ValueError("确认答案包含后端未要求的字段。")
        normalized: list[dict[str, Any]] = []
        for field, question in expected.items():
            value = answers.get(field)
            if self._is_empty_answer(value):
                if question.get("required", True):
                    raise ValueError(f"请填写：{question.get('label') or field}。")
                normalized.append(
                    {
                        "field": field,
                        "label": question.get("label"),
                        "value": None,
                        "selected_labels": [],
                    }
                )
                continue
            normalized_value, selected_labels = self._validate_answer(question, value)
            normalized.append(
                {
                    "field": field,
                    "label": question.get("label"),
                    "value": normalized_value,
                    "selected_labels": selected_labels,
                }
            )

        with self._clarification_lock:
            self._clarifications.pop(clarification_id, None)
        return "\n\n".join(
            [
                f"用户原始问题：\n{pending.original_question}",
                "用户已完成后端要求的结构化澄清，以下JSON是本轮确认事实：\n"
                + json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
                "请结合原始问题和确认事实重新生成完整QueryPlan；不得再次询问已经确认的字段。",
            ]
        )

    @staticmethod
    def _is_empty_answer(value: Any) -> bool:
        return value is None or value == "" or value == []

    @staticmethod
    def _validate_answer(
        question: dict[str, Any],
        value: Any,
    ) -> tuple[Any, list[str]]:
        answer_type = question.get("type")
        options = question.get("options") if isinstance(question.get("options"), list) else []
        option_labels = {
            str(item.get("value")): str(item.get("label"))
            for item in options
            if isinstance(item, dict) and item.get("value") is not None
        }
        if answer_type == "single_select":
            selected = str(value)
            if selected not in option_labels:
                raise ValueError("确认答案不在后端提供的候选项中。")
            return selected, [option_labels[selected]]
        if answer_type == "multi_select":
            if not isinstance(value, list) or not value:
                raise ValueError("请至少选择一个后端提供的候选项。")
            selected = [str(item) for item in value]
            if len(set(selected)) != len(selected) or any(item not in option_labels for item in selected):
                raise ValueError("确认答案包含无效或重复的候选项。")
            return selected, [option_labels[item] for item in selected]
        if answer_type == "date":
            try:
                from datetime import date

                date.fromisoformat(str(value))
            except ValueError as exc:
                raise ValueError("日期必须使用YYYY-MM-DD格式。") from exc
            return str(value), []
        if answer_type == "text":
            text = str(value).strip()
            if len(text) > 500:
                raise ValueError("补充说明不能超过500个字符。")
            return text, []
        raise ValueError("后端返回了不支持的确认控件类型。")

    def _discard_expired_clarifications(self) -> None:
        cutoff = monotonic() - self._clarification_ttl_seconds
        expired = [key for key, value in self._clarifications.items() if value.created_at < cutoff]
        for key in expired:
            self._clarifications.pop(key, None)

    def _metadata(
        self,
        plan_result: QueryPlanResult,
        failure_reason: str | None = None,
    ) -> QueryMetadata:
        return QueryMetadata(
            configured_mode="query_plan",
            executed_generator="query_planner",
            route="QueryPlan",
            failure_reason=failure_reason,
            provider=self.provider_name,
            model=plan_result.model,
            llm_latency_ms=plan_result.latency_ms,
            query_plan=plan_result.query_plan,
            plan_repair_attempted=plan_result.repair_attempted,
        )

    @staticmethod
    def _status_error(status_code: object, status: object) -> ErrorDetail:
        status_dict = status if isinstance(status, dict) else {}
        reason = status_dict.get("reason")
        clarification = status_dict.get("clarification_question")
        if status_code == "clarification_required":
            return ErrorDetail(
                code="CLARIFICATION_REQUIRED",
                message=str(clarification or reason or "请补充完成查询所需的信息。"),
                retryable=False,
            )
        if status_code == "pending_project_definition":
            return ErrorDetail(
                code="PENDING_PROJECT_DEFINITION",
                message=str(reason or "该问题依赖尚未确认的项目业务口径。"),
                retryable=False,
            )
        if status_code == "data_unavailable":
            return ErrorDetail(
                code="DATA_UNAVAILABLE",
                message=str(reason or "完成该问题所需的数据不在正式数据范围内。"),
                retryable=False,
            )
        return ErrorDetail(
            code="LLM_PROVIDER_ERROR",
            message="查询规划器返回了无法识别的状态。",
            retryable=False,
        )

    def _record(
        self,
        command: QueryCommand,
        event_type: str,
        error_code: str | None = None,
    ) -> None:
        try:
            self.audit_logger.record(
                AuditEvent(
                    event_type=event_type,
                    request_id=command.request_id,
                    user_id=command.user_id,
                    question=command.question,
                    error_code=error_code,
                )
            )
        except Exception:
            return None
