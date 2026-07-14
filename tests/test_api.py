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
from app.application.models import GeneratedSQL, QueryContext
from app.application.errors import QueryExecutionError
from app.application.pipeline import QueryPipeline
from app.core.settings import Settings
from app.main import app


ROOT = Path(__file__).resolve().parents[1]


class DangerousGenerator:
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        return GeneratedSQL("DELETE FROM customer_info", generator_name="dangerous-test")


class BrokenExecutor:
    def execute_query(self, sql: str, parameters: dict, max_rows: int = 1000):
        raise QueryExecutionError("数据库查询执行失败。")


class BuggyPipeline:
    def run(self, command):
        raise RuntimeError("programming bug")


class QueryAPITest(unittest.TestCase):
    def setUp(self) -> None:
        from app.api.query import get_query_pipeline
        from app.bootstrap.container import build_pipeline

        self.get_query_pipeline = get_query_pipeline
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "bankinsight.db"
        initialize_database(self.database_path, ROOT / "sql" / "schema.sql")
        self.pipeline = build_pipeline(
            self.database_path, settings=Settings(generator_mode="rule")
        )
        app.dependency_overrides[get_query_pipeline] = lambda: self.pipeline
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.tempdir.cleanup()

    def test_health_and_three_supported_questions(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)

        cases = [
            ("查询有效客户数量", [[2]], "当前有效客户数量为2户。"),
            (
                "查询客户C001的账户余额",
                [["C001", 6_000_000]],
                "客户C001当前有效账户余额合计为600.00万元。",
            ),
            (
                "查询客户C001在2026年6月的交易汇总",
                [["C001", 3, 100_000, 50_000, 50_000]],
                "客户C001在该期间共有3笔成功交易，流入10.00万元，流出5.00万元，净流入5.00万元。",
            ),
        ]
        for question, expected_rows, expected_summary in cases:
            with self.subTest(question=question):
                response = self.client.post(
                    "/api/v1/query",
                    json={
                        "question": question,
                        "user_id": "demo_user",
                        "conversation_id": "demo_session",
                    },
                )
                body = response.json()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(body["rows"], expected_rows)
                self.assertEqual(body["summary"], expected_summary)
                self.assertIsNone(body["error"])
                self.assertEqual(
                    set(body),
                    {
                        "request_id",
                        "question",
                        "sql",
                        "columns",
                        "rows",
                        "summary",
                        "warnings",
                        "error",
                        "metadata",
                    },
                )

    def test_unsupported_question_is_structured_400(self) -> None:
        response = self._post("预测明年的股票价格")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "UNSUPPORTED_QUESTION")

    def test_dangerous_sql_is_structured_403(self) -> None:
        dangerous_pipeline = QueryPipeline(
            context_resolver=YAMLContextResolver(
                ROOT / "config" / "schema.yml", ROOT / "config" / "metrics.yml"
            ),
            sql_generator=DangerousGenerator(),
            safety_checker=SQLGlotSafetyChecker(),
            database_executor=SQLiteExecutor(self.database_path),
            result_formatter=TemplateResultFormatter(),
            audit_logger=NoOpAuditLogger(),
        )
        app.dependency_overrides[self.get_query_pipeline] = lambda: dangerous_pipeline

        response = self._post("删除全部客户")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "SQL_REJECTED")
        self.assertEqual(
            response.json()["error"]["message"],
            "生成的查询未通过只读安全检查。",
        )

    def test_missing_database_is_structured_503(self) -> None:
        from app.bootstrap.container import build_pipeline

        app.dependency_overrides[self.get_query_pipeline] = lambda: build_pipeline(
            Path(self.tempdir.name) / "missing.db"
        )
        response = self._post("查询有效客户数量")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_UNAVAILABLE")

    def test_database_execution_error_is_structured_500(self) -> None:
        broken_pipeline = QueryPipeline(
            context_resolver=YAMLContextResolver(
                ROOT / "config" / "schema.yml", ROOT / "config" / "metrics.yml"
            ),
            sql_generator=RuleSQLGenerator(),
            safety_checker=SQLGlotSafetyChecker(),
            database_executor=BrokenExecutor(),
            result_formatter=TemplateResultFormatter(),
            audit_logger=NoOpAuditLogger(),
        )
        app.dependency_overrides[self.get_query_pipeline] = lambda: broken_pipeline

        response = self._post("查询有效客户数量")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "QUERY_EXECUTION_ERROR")
        self.assertNotIn("sqlite", response.text.lower())

    def test_ask_compatibility_alias_uses_same_contract(self) -> None:
        response = self.client.post(
            "/api/v1/ask",
            json={"question": "查询有效客户数量", "user_id": "demo_user"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"], [[2]])

    def test_validation_error_uses_common_response_shape(self) -> None:
        for invalid_question in ("", "   "):
            with self.subTest(question=repr(invalid_question)):
                response = self.client.post(
                    "/api/v1/query",
                    json={"question": invalid_question, "user_id": "demo_user"},
                )
                body = response.json()
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    body["error"]["code"], "REQUEST_VALIDATION_ERROR"
                )
                self.assertEqual(body["rows"], [])
                self.assertEqual(
                    set(body),
                    {
                        "request_id",
                        "question",
                        "sql",
                        "columns",
                        "rows",
                        "summary",
                        "warnings",
                        "error",
                        "metadata",
                    },
                )

    def test_unexpected_programming_error_is_handled_by_api(self) -> None:
        app.dependency_overrides[self.get_query_pipeline] = lambda: BuggyPipeline()
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.post(
                "/api/v1/query",
                json={"question": "查询有效客户数量", "user_id": "demo_user"},
            )
        finally:
            client.close()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("programming bug", response.text)

    def test_valid_question_preserves_original_text(self) -> None:
        original = "  查询有效客户数量  "
        response = self.client.post(
            "/api/v1/query",
            json={"question": original, "user_id": "demo_user"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["question"], original)

    def _post(self, question: str):
        return self.client.post(
            "/api/v1/query",
            json={"question": question, "user_id": "demo_user"},
        )


if __name__ == "__main__":
    unittest.main()
