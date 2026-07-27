from __future__ import annotations

import json
import logging

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

    def run(self, command: QueryCommand) -> QueryOutcome:
        logger.info(
            "planned_query_received request_id=%s question=%s",
            command.request_id,
            command.question,
        )
        self._record(command, "request_started")
        metadata: QueryMetadata | None = None
        try:
            logger.info("llm_query_planner_call request_id=%s", command.request_id)
            plan_result = self.query_planner.plan(command.question)
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
                return QueryOutcome(
                    request_id=command.request_id,
                    question=command.question,
                    error=error,
                    metadata=metadata,
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
