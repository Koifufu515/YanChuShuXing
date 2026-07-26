from __future__ import annotations

from dataclasses import replace

from app.application.errors import ApplicationError
from app.application.models import (
    AuditEvent,
    ErrorDetail,
    QueryCommand,
    QueryOutcome,
    UserContext,
)
from app.ports.audit_logger import AuditLogger
from app.ports.context_resolver import ContextResolver
from app.ports.database_executor import DatabaseExecutor
from app.ports.result_formatter import ResultFormatter
from app.ports.sql_generator import SQLGenerator
from app.ports.sql_safety import SQLSafetyChecker
from app.ports.intent_confirmation import IntentConfirmationResolver


class QueryPipeline:
    def __init__(
        self,
        context_resolver: ContextResolver,
        sql_generator: SQLGenerator,
        safety_checker: SQLSafetyChecker,
        database_executor: DatabaseExecutor,
        result_formatter: ResultFormatter,
        audit_logger: AuditLogger,
        intent_confirmation_resolver: IntentConfirmationResolver | None = None,
    ) -> None:
        self.context_resolver = context_resolver
        self.sql_generator = sql_generator
        self.safety_checker = safety_checker
        self.database_executor = database_executor
        self.result_formatter = result_formatter
        self.audit_logger = audit_logger
        self.intent_confirmation_resolver = intent_confirmation_resolver

    def run(self, command: QueryCommand) -> QueryOutcome:
        self._record(command, "request_started")
        sql: str | None = None
        try:
            execution_question = command.question
            confirmation_payload = None
            if self.intent_confirmation_resolver is not None:
                resolution = self.intent_confirmation_resolver.resolve(
                    command.question, command.confirmation
                )
                confirmation_payload = resolution.confirmation
                if resolution.status == "required":
                    error = ErrorDetail(
                        code="CLARIFICATION_REQUIRED",
                        message="请确认缺少或存在歧义的分析条件后再查询。",
                        retryable=False,
                    )
                    self._record(command, "clarification_required", error_code=error.code)
                    return QueryOutcome(
                        request_id=command.request_id,
                        question=command.question,
                        sql=None,
                        error=error,
                        confirmation=confirmation_payload,
                    )
                if resolution.execution_question:
                    execution_question = resolution.execution_question
            context = self.context_resolver.resolve(execution_question)
            generated = self.sql_generator.generate(execution_question, context)
            sql = generated.sql
            safety = self.safety_checker.validate(
                generated.sql,
                UserContext(
                    user_id=command.user_id,
                    allowed_tables=context.allowed_tables,
                    denied_columns=context.denied_columns,
                ),
            )
            warnings = [*generated.warnings, *safety.warnings]
            if not safety.allowed:
                error = ErrorDetail(
                    code=safety.error_code or "SQL_REJECTED",
                    message="生成的查询未通过只读安全检查。",
                    retryable=False,
                )
                self._record(
                    command, "query_rejected", sql=sql, error_code=error.code
                )
                return QueryOutcome(
                    request_id=command.request_id,
                    question=command.question,
                    sql=sql,
                    warnings=warnings,
                    error=error,
                    metadata=(
                        replace(generated.metadata, failure_reason="unsafe_sql")
                        if generated.metadata
                        else None
                    ),
                )

            result = self.database_executor.execute_query(
                generated.sql, generated.parameters, max_rows=1000
            )
            formatted = self.result_formatter.format(command.question, result)
            summary = formatted.summary
            if confirmation_payload and confirmation_payload.get("status") == "confirmed":
                conditions = confirmation_payload.get("final_conditions", {})
                metric = conditions.get("metric", {}).get("label", "暂未提供")
                method = conditions.get("growth_method", {}).get("label", "暂未提供")
                period = conditions.get("comparison_period", {})
                prefix = f"最终采用条件：{metric}，{method}，{period.get('start_date', '暂未提供')} 至 {period.get('end_date', '暂未提供')}，按增长额进行机构排名。"
                summary = f"{prefix}{summary or ''}"
            self._record(command, "query_succeeded", sql=sql)
            return QueryOutcome(
                request_id=command.request_id,
                question=command.question,
                sql=sql,
                columns=result.columns,
                rows=result.rows,
                summary=summary,
                warnings=[*warnings, *formatted.warnings],
                metadata=(
                    replace(
                        generated.metadata,
                        query_duration_ms=round(result.duration_ms, 3),
                    )
                    if generated.metadata
                    else None
                ),
                confirmation=confirmation_payload,
            )
        except ApplicationError as exc:
            error = ErrorDetail(
                code=exc.code,
                message=exc.public_message,
                retryable=exc.retryable,
            )
            self._record(command, "query_failed", sql=sql, error_code=error.code)
            return QueryOutcome(
                request_id=command.request_id,
                question=command.question,
                sql=sql,
                error=error,
                metadata=exc.metadata,
                confirmation=None,
            )
        except Exception:
            self._record(command, "query_failed", sql=sql, error_code="INTERNAL_ERROR")
            raise

    def _record(
        self,
        command: QueryCommand,
        event_type: str,
        sql: str | None = None,
        error_code: str | None = None,
    ) -> None:
        try:
            self.audit_logger.record(
                AuditEvent(
                    event_type=event_type,
                    request_id=command.request_id,
                    user_id=command.user_id,
                    question=command.question,
                    sql=sql,
                    error_code=error_code,
                )
            )
        except Exception:
            return None
