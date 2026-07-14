import inspect
import unittest

from app.application.errors import QueryExecutionError, UnsupportedQuestionError
from app.application.models import (
    AuditEvent,
    FormattedResult,
    GeneratedSQL,
    QueryCommand,
    QueryContext,
    QueryResult,
    SafetyResult,
)


class StaticResolver:
    def resolve(self, question: str) -> QueryContext:
        return QueryContext("schema", "metrics", frozenset({"customer_info"}))


class StaticGenerator:
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        return GeneratedSQL(
            "SELECT COUNT(*) AS customer_count FROM customer_info",
            generator_name="fake",
        )


class UnsupportedGenerator:
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        raise UnsupportedQuestionError("不支持该问题。")


class BuggyGenerator:
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        raise RuntimeError("programming bug")


class AllowSafety:
    def validate(self, sql: str, user_context: object) -> SafetyResult:
        return SafetyResult(True, referenced_tables=["customer_info"])


class RejectSafety:
    def validate(self, sql: str, user_context: object) -> SafetyResult:
        return SafetyResult(False, error_code="SQL_REJECTED", error_message="危险SQL")


class StaticExecutor:
    def execute_query(self, sql: str, parameters: dict, max_rows: int = 1000) -> QueryResult:
        return QueryResult(["customer_count"], [[2]], 1, False, 1.0)


class FailingExecutor:
    def execute_query(self, sql: str, parameters: dict, max_rows: int = 1000) -> QueryResult:
        raise AssertionError("安全拒绝后不应调用数据库")


class ErrorExecutor:
    def execute_query(self, sql: str, parameters: dict, max_rows: int = 1000) -> QueryResult:
        raise QueryExecutionError("数据库查询执行失败。")


class StaticFormatter:
    def format(self, question: str, result: QueryResult) -> FormattedResult:
        return FormattedResult("当前有效客户数量为2户。")


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class QueryPipelineTest(unittest.TestCase):
    def test_successful_query_returns_outcome_and_audit_events(self) -> None:
        audit = RecordingAudit()
        pipeline = self._pipeline(audit=audit)

        outcome = pipeline.run(self._command())

        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.rows, [[2]])
        self.assertEqual(outcome.summary, "当前有效客户数量为2户。")
        self.assertEqual(
            [event.event_type for event in audit.events],
            ["request_started", "query_succeeded"],
        )

    def test_safety_rejection_short_circuits_database(self) -> None:
        audit = RecordingAudit()
        pipeline = self._pipeline(
            safety=RejectSafety(), executor=FailingExecutor(), audit=audit
        )

        outcome = pipeline.run(self._command())

        self.assertEqual(outcome.error.code, "SQL_REJECTED")
        self.assertEqual(audit.events[-1].event_type, "query_rejected")

    def test_known_errors_are_structured(self) -> None:
        unsupported_audit = RecordingAudit()
        database_audit = RecordingAudit()
        unsupported = self._pipeline(
            generator=UnsupportedGenerator(), audit=unsupported_audit
        ).run(self._command())
        database_error = self._pipeline(
            executor=ErrorExecutor(), audit=database_audit
        ).run(self._command())

        self.assertEqual(unsupported.error.code, "UNSUPPORTED_QUESTION")
        self.assertEqual(database_error.error.code, "QUERY_EXECUTION_ERROR")
        self.assertIsNotNone(database_error.sql)
        self.assertEqual(unsupported_audit.events[-1].event_type, "query_failed")
        self.assertEqual(database_audit.events[-1].event_type, "query_failed")

    def test_pipeline_has_no_concrete_adapter_or_infrastructure_imports(self) -> None:
        from app.application import pipeline as pipeline_module

        source = inspect.getsource(pipeline_module).lower()
        for forbidden in ("app.adapters", "fastapi", "sqlite3", "sqlglot"):
            self.assertNotIn(forbidden, source)

    def test_unexpected_programming_errors_are_audited_and_reraised(self) -> None:
        audit = RecordingAudit()
        pipeline = self._pipeline(generator=BuggyGenerator(), audit=audit)

        with self.assertRaisesRegex(RuntimeError, "programming bug"):
            pipeline.run(self._command())

        self.assertEqual(
            [event.event_type for event in audit.events],
            ["request_started", "query_failed"],
        )
        self.assertEqual(audit.events[-1].error_code, "INTERNAL_ERROR")

    @staticmethod
    def _command() -> QueryCommand:
        return QueryCommand("查询有效客户数量", "user1", "session1", "req1")

    @staticmethod
    def _pipeline(
        resolver=None,
        generator=None,
        safety=None,
        executor=None,
        formatter=None,
        audit=None,
    ):
        from app.application.pipeline import QueryPipeline

        return QueryPipeline(
            context_resolver=resolver or StaticResolver(),
            sql_generator=generator or StaticGenerator(),
            safety_checker=safety or AllowSafety(),
            database_executor=executor or StaticExecutor(),
            result_formatter=formatter or StaticFormatter(),
            audit_logger=audit or RecordingAudit(),
        )


if __name__ == "__main__":
    unittest.main()
