from __future__ import annotations

from app.adapters.security.institution_scope import (
    InstitutionAccessDeniedError,
    evaluate_institution_access,
)
from app.adapters.security.result_security import (
    secure_result,
)
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
from app.ports.answer_composer import AnswerComposer
from app.ports.query_plan_executor import QueryPlanExecutor
from app.ports.query_planner import QueryPlanner


class PlannedQueryPipeline:
    """正式数据环境的查询规划、确定性执行与结构化返回链路。"""

    def __init__(
        self,
        query_planner: QueryPlanner,
        query_plan_executor: QueryPlanExecutor,
        audit_logger: AuditLogger,
        provider_name: str = "deepseek",
        answer_composer: AnswerComposer | None = None,
    ) -> None:
        self.query_planner = query_planner
        self.query_plan_executor = query_plan_executor
        self.audit_logger = audit_logger
        self.answer_composer = answer_composer
        self.provider_name = provider_name

    def run(self, command: QueryCommand) -> QueryOutcome:
        self._record(command, "request_started")
        metadata: QueryMetadata | None = None
        try:
            plan_result = self.query_planner.plan(command.question)
            metadata = self._metadata(plan_result)

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

            if command.security_principal is not None:
                access_decision = (
                    evaluate_institution_access(
                        plan_result.query_plan,
                        command.security_principal,
                    )
                )

                if not access_decision.allowed:
                    self._record(
                        command,
                        "access_denied",
                        error_code="ACCESS_DENIED",
                        security_action=(
                            "institution_scope_denied"
                        ),
                        referenced_institution_count=len(
                            access_decision
                            .referenced_institution_ids
                        ),
                    )

                    raise InstitutionAccessDeniedError(
                        access_decision.reason
                    )

            execution = self.query_plan_executor.execute(
                plan_result.query_plan
            )

            columns = execution.columns
            rows = execution.rows
            summary = execution.summary
            warnings = list(execution.warnings)
            protected_result = False

            if command.security_principal is not None:
                secured_result = secure_result(
                    columns=execution.columns,
                    rows=execution.rows,
                    principal=command.security_principal,
                )

                columns = secured_result.columns
                rows = secured_result.rows

                if secured_result.removed_columns:
                    protected_result = True
                    warnings.append(
                        "部分字段已根据当前岗位权限移除。"
                    )
                    self._record(
                        command,
                        "result_secured",
                        security_action=(
                            "field_access_filtered"
                        ),
                        affected_column_count=len(
                            secured_result
                            .removed_columns
                        ),
                    )

                if secured_result.masked_columns:
                    protected_result = True
                    warnings.append(
                        "部分字段已根据当前岗位执行动态脱敏。"
                    )
                    self._record(
                        command,
                        "result_secured",
                        security_action=(
                            "dynamic_masking"
                        ),
                        affected_column_count=len(
                            secured_result
                            .masked_columns
                        ),
                    )

                if protected_result:
                    summary = (
                        "查询成功，结果已根据当前身份完成"
                        "字段权限控制和动态脱敏。"
                    )

            answer = (
                self.answer_composer.compose(
                    command.question,
                    plan_result.query_plan,
                    execution.analysis_facts,
                )
                if self.answer_composer is not None
                and execution.analysis_facts is not None
                and not protected_result
                else None
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
                columns=columns,
                rows=rows,
                summary=summary,
                warnings=warnings,
                metadata=metadata,
                answer=answer,
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
        security_action: str | None = None,
        affected_column_count: int | None = None,
        referenced_institution_count: int | None = None,
    ) -> None:
        principal = command.security_principal

        try:
            self.audit_logger.record(
                AuditEvent(
                    event_type=event_type,
                    request_id=command.request_id,
                    user_id=command.user_id,
                    question=command.question,
                    error_code=error_code,
                    actor_role=(
                        principal.role
                        if principal is not None
                        else None
                    ),
                    authenticated=(
                        principal.authenticated
                        if principal is not None
                        else None
                    ),
                    security_action=security_action,
                    masking_profile=(
                        principal.masking_profile
                        if principal is not None
                        else None
                    ),
                    affected_column_count=(
                        affected_column_count
                    ),
                    referenced_institution_count=(
                        referenced_institution_count
                    ),
                )
            )
        except Exception:
            return None
