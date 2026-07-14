import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.query import get_query_pipeline
from app.application.errors import ProviderTimeoutError
from app.application.models import LLMResponse
from app.bootstrap.container import build_pipeline
from app.core.settings import Settings


class FakeLLMProvider:
    def __init__(self, sql=None):
        self.calls = 0
        self.sql = sql or (
            "SELECT COUNT(DISTINCT customer_id) AS customer_count "
            "FROM customer_info WHERE customer_status = :status"
        )

    def complete(self, request):
        self.calls += 1
        if self.calls % 2 == 1:
            text = json.dumps(
                {
                    "intent": "active_customer_count",
                    "business_domain": "customer",
                    "metrics": ["active_customer_count"],
                    "dimensions": [],
                    "filters": {"customer_status": "ACTIVE"},
                    "time_range": None,
                    "sort": [],
                    "limit": None,
                    "clarification_required": False,
                    "clarification_question": None,
                }
            )
        else:
            text = json.dumps(
                {
                    "sql": self.sql,
                    "parameters": {"status": "ACTIVE"},
                    "warnings": [],
                }
            )
        return LLMResponse(text=text, model="fake-model", latency_ms=5)


class TimeoutProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        raise ProviderTimeoutError("private timeout")


class SemanticOnlyProvider:
    def __init__(self, semantic):
        self.semantic = semantic
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return LLMResponse(
            text=json.dumps(self.semantic), model="fake-model", latency_ms=5
        )


class GeneratorModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.adapters.database.init_db import initialize_database

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.temp_dir.name) / "demo.db"
        initialize_database(
            cls.database_path,
            Path(__file__).resolve().parents[1] / "sql" / "schema.sql",
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _settings(self, mode):
        return Settings(generator_mode=mode, llm_api_key="fake-key")

    def test_rule_llm_and_hybrid_keep_api_v1_response_contract(self):
        from app.main import app

        expected_keys = {
            "request_id", "question", "sql", "columns", "rows",
            "summary", "warnings", "error", "metadata",
        }
        for mode in ("rule", "llm", "hybrid"):
            with self.subTest(mode=mode):
                provider = FakeLLMProvider()
                pipeline = build_pipeline(
                    database_path=self.database_path,
                    settings=self._settings(mode),
                    llm_provider=provider,
                )
                app.dependency_overrides[get_query_pipeline] = lambda: pipeline
                try:
                    response = TestClient(app).post(
                        "/api/v1/query",
                        json={
                            "question": "查询有效客户数量",
                            "user_id": "demo_user",
                            "conversation_id": "mode_test",
                        },
                    )
                finally:
                    app.dependency_overrides.pop(get_query_pipeline, None)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.json()), expected_keys)
                self.assertEqual(response.json()["rows"], [[2]])
                metadata = response.json()["metadata"]
                self.assertEqual(metadata["configured_mode"], mode)
                self.assertEqual(
                    metadata["executed_generator"],
                    "llm" if mode == "llm" else "rule",
                )
                self.assertFalse(metadata["fallback"]["used"])
                self.assertEqual(provider.calls, 2 if mode == "llm" else 0)
                self.assertEqual(metadata["route"], "LLM" if mode == "llm" else "Rule")
                self.assertEqual(metadata["rule_matched"], mode != "llm")
                self.assertIsNone(metadata["failure_reason"])

    def test_llm_generated_dangerous_sql_is_rejected_by_existing_safety(self):
        provider = FakeLLMProvider(sql="DELETE FROM customer_info")
        pipeline = build_pipeline(
            database_path=self.database_path,
            settings=self._settings("hybrid"),
            llm_provider=provider,
        )
        from app.application.models import QueryCommand

        outcome = pipeline.run(
            QueryCommand("当前有效客户数量是多少", "u", None, "req")
        )
        self.assertEqual(outcome.error.code, "SQL_REJECTED")
        self.assertEqual(outcome.rows, [])
        self.assertEqual(outcome.metadata.route, "LLM")
        self.assertEqual(outcome.metadata.failure_reason, "unsafe_sql")

    def test_hybrid_llm_timeout_is_terminal_and_keeps_routing_metadata(self):
        provider = TimeoutProvider()
        pipeline = build_pipeline(
            database_path=self.database_path,
            settings=self._settings("hybrid"),
            llm_provider=provider,
        )
        from app.application.models import QueryCommand

        outcome = pipeline.run(
            QueryCommand("当前有效客户数量是多少", "u", None, "req")
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(outcome.error.code, "LLM_TIMEOUT")
        self.assertTrue(outcome.error.retryable)
        self.assertEqual(outcome.metadata.route, "LLM")
        self.assertFalse(outcome.metadata.rule_matched)
        self.assertEqual(outcome.metadata.failure_reason, "llm_timeout")
        self.assertFalse(outcome.metadata.fallback.used)

    def test_hybrid_missing_parameters_asks_for_clarification(self):
        provider = SemanticOnlyProvider(
            {
                "intent": "loan_analysis",
                "business_domain": "loan",
                "metrics": [],
                "dimensions": [],
                "filters": {},
                "time_range": None,
                "sort": [],
                "limit": None,
                "clarification_required": True,
                "clarification_question": "请补充时间范围或分行。",
            }
        )
        pipeline = build_pipeline(
            database_path=self.database_path,
            settings=self._settings("hybrid"),
            llm_provider=provider,
        )
        from app.application.models import QueryCommand

        outcome = pipeline.run(QueryCommand("帮我分析贷款", "u", None, "req"))
        self.assertEqual(outcome.error.code, "CLARIFICATION_REQUIRED")
        self.assertEqual(outcome.error.message, "请补充时间范围或分行。")
        self.assertEqual(outcome.metadata.failure_reason, "missing_parameter")
        self.assertEqual(outcome.metadata.route, "LLM")

    def test_hybrid_unsupported_metric_is_structured(self):
        provider = SemanticOnlyProvider(
            {
                "intent": "loan_analysis",
                "business_domain": "loan",
                "metrics": ["non_performing_loan_ratio"],
                "dimensions": [],
                "filters": {},
                "time_range": None,
                "sort": [],
                "limit": None,
                "clarification_required": False,
                "clarification_question": None,
            }
        )
        pipeline = build_pipeline(
            database_path=self.database_path,
            settings=self._settings("hybrid"),
            llm_provider=provider,
        )
        from app.application.models import QueryCommand

        outcome = pipeline.run(QueryCommand("查询不良贷款率", "u", None, "req"))
        self.assertEqual(outcome.error.code, "UNSUPPORTED_METRIC")
        self.assertEqual(outcome.metadata.failure_reason, "unsupported_metric")

    def test_hybrid_rule_match_does_not_require_llm_configuration(self):
        pipeline = build_pipeline(
            database_path=self.database_path,
            settings=Settings(generator_mode="hybrid", llm_api_key=""),
        )
        from app.application.models import QueryCommand

        outcome = pipeline.run(QueryCommand("查询有效客户数量", "u", None, "req"))
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.rows, [[2]])
        self.assertFalse(outcome.metadata.fallback.used)
        self.assertTrue(outcome.metadata.rule_matched)
        self.assertEqual(outcome.metadata.route, "Rule")

    def test_llm_missing_configuration_returns_structured_error(self):
        pipeline = build_pipeline(
            database_path=self.database_path,
            settings=Settings(generator_mode="llm", llm_api_key=""),
        )
        from app.application.models import QueryCommand

        outcome = pipeline.run(QueryCommand("查询有效客户数量", "u", None, "req"))
        self.assertEqual(outcome.error.code, "CONFIGURATION_ERROR")


if __name__ == "__main__":
    unittest.main()
