import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.audit.noop_logger import NoOpAuditLogger
from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.database.init_db import initialize_database
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.formatting.template_formatter import TemplateResultFormatter
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.errors import QueryTimeoutError
from app.application.models import GeneratedSQL, QueryContext
from app.application.pipeline import QueryPipeline
from app.bootstrap.container import build_pipeline
from app.core.settings import Settings
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


class DangerousGenerator:
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        return GeneratedSQL("DROP TABLE customer_info", generator_name="special-case")


class TimeoutExecutor:
    def execute_query(self, sql: str, parameters: dict, max_rows: int = 1000):
        raise QueryTimeoutError("数据库查询超时。")


class SpecialCaseSuite(unittest.TestCase):
    """Issue #6 交付物3：固定专项测试用例库（独立于官方题库，可公开运行）。"""

    def setUp(self) -> None:
        from app.api.query import get_query_pipeline

        self.get_query_pipeline = get_query_pipeline
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "bankinsight.db"
        initialize_database(self.database_path, ROOT / "sql" / "schema.sql")
        self.pipeline = build_pipeline(
            self.database_path, settings=Settings(generator_mode="rule")
        )
        app.dependency_overrides[self.get_query_pipeline] = lambda: self.pipeline
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.tempdir.cleanup()

    def _post(self, question: str):
        return self.client.post(
            "/api/v1/query", json={"question": question, "user_id": "special_case"}
        )

    def _override_pipeline(self, **kwargs) -> None:
        defaults = dict(
            context_resolver=YAMLContextResolver(
                ROOT / "config" / "schema.yml", ROOT / "config" / "metrics.yml"
            ),
            sql_generator=RuleSQLGenerator(),
            safety_checker=SQLGlotSafetyChecker(),
            database_executor=SQLiteExecutor(self.database_path),
            result_formatter=TemplateResultFormatter(),
            audit_logger=NoOpAuditLogger(),
        )
        defaults.update(kwargs)
        app.dependency_overrides[self.get_query_pipeline] = lambda: QueryPipeline(
            **defaults
        )

    def test_empty_and_blank_question_returns_structured_422(self) -> None:
        for question in ("", "   "):
            with self.subTest(question=repr(question)):
                response = self._post(question)
                self.assertEqual(response.status_code, 422)
                body = response.json()
                self.assertEqual(body["error"]["code"], "REQUEST_VALIDATION_ERROR")
                self.assertEqual(body["rows"], [])

    def test_overlong_question_returns_structured_422(self) -> None:
        response = self._post("查" * 501)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"], "REQUEST_VALIDATION_ERROR"
        )

    def test_unknown_customer_returns_empty_result_not_error(self) -> None:
        response = self._post("查询客户C999的账户余额")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["error"])
        self.assertEqual(body["rows"], [])

    def test_out_of_range_period_returns_empty_result_not_error(self) -> None:
        response = self._post("查询客户C001在2030年1月的交易汇总")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["error"])
        self.assertTrue(
            body["rows"] == [] or body["rows"][0][1] == 0,
            "rows 应为空列表或聚合零行",
        )

    def test_dangerous_sql_rejected_and_database_untouched(self) -> None:
        self._override_pipeline(sql_generator=DangerousGenerator())
        response = self._post("删除客户表")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "SQL_REJECTED")

        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM customer_info"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 3)

    def test_query_timeout_returns_structured_504(self) -> None:
        self._override_pipeline(database_executor=TimeoutExecutor())
        response = self._post("查询有效客户数量")
        self.assertEqual(response.status_code, 504)
        body = response.json()
        self.assertEqual(body["error"]["code"], "QUERY_TIMEOUT")
        self.assertTrue(body["error"]["retryable"])

    def test_missing_database_returns_structured_503(self) -> None:
        app.dependency_overrides[self.get_query_pipeline] = lambda: build_pipeline(
            Path(self.tempdir.name) / "missing.db",
            settings=Settings(generator_mode="rule"),
        )
        response = self._post("查询有效客户数量")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_UNAVAILABLE")

    def test_error_responses_do_not_leak_internals(self) -> None:
        self._override_pipeline(database_executor=TimeoutExecutor())
        response = self._post("查询有效客户数量")
        lowered = response.text.lower()
        for forbidden in ("traceback", "sqlite", 'file "'):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
