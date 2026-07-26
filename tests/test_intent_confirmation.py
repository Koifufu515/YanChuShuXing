from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.audit.noop_logger import NoOpAuditLogger
from app.adapters.context.real_database_resolver import RealDatabaseContextResolver
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.formatting.real_result_formatter import RealResultFormatter
from app.adapters.generation.real_rule_generator import RealRuleSQLGenerator
from app.adapters.intent_confirmation import RealIntentConfirmationResolver
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.models import QueryCommand
from app.application.pipeline import QueryPipeline
from app.main import app


class CountingExecutor:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def execute_query(self, sql, parameters, max_rows=1000):
        self.calls += 1
        return self.inner.execute_query(sql, parameters, max_rows)


class IntentConfirmationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "real.db"
        self._create_database()
        self.executor = CountingExecutor(SQLiteExecutor(self.database))
        self.pipeline = QueryPipeline(
            context_resolver=RealDatabaseContextResolver(self.database),
            sql_generator=RealRuleSQLGenerator(),
            safety_checker=SQLGlotSafetyChecker(),
            database_executor=self.executor,
            result_formatter=RealResultFormatter(),
            audit_logger=NoOpAuditLogger(),
            intent_confirmation_resolver=RealIntentConfirmationResolver(self.database),
        )

    def tearDown(self):
        app.dependency_overrides.clear()
        self.temp.cleanup()

    def test_explicit_single_and_ranking_still_query_directly(self):
        cases = (
            "查询江苏省A市农商行在2026-04-30的各项存款余额",
            "查询2026-04-30各项存款余额机构排名",
        )
        for index, question in enumerate(cases):
            outcome = self.pipeline.run(QueryCommand(question, "u", "c", f"d{index}"))
            self.assertIsNone(outcome.error)
            self.assertIsNone(outcome.confirmation)
        self.assertEqual(self.executor.calls, 2)

    def test_ambiguous_growth_returns_four_state_plan_without_sql_or_database(self):
        outcome = self._ask("哪家银行存款增长最好？")
        self.assertEqual(outcome.error.code, "CLARIFICATION_REQUIRED")
        self.assertIsNone(outcome.sql)
        self.assertEqual(self.executor.calls, 0)
        fields = {item["key"]: item for item in outcome.confirmation["fields"]}
        self.assertEqual(fields["metric"]["state"], "recognized")
        self.assertEqual(fields["metric"]["value"]["id"], "ZB001")
        self.assertEqual(fields["analysis"]["state"], "recognized")
        self.assertEqual(fields["growth_method"]["state"], "recognized")
        self.assertEqual(fields["comparison_period"]["state"], "missing")
        self.assertTrue(fields["comparison_period"]["options"])

    def test_confirmed_growth_ranking_queries_real_rows(self):
        pending = self._ask("哪家银行存款增长最好？")
        outcome = self._ask(
            "哪家银行存款增长最好？",
            {
                "token": pending.confirmation["token"],
                "selections": {"comparison_period": "full_range"},
            },
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(self.executor.calls, 1)
        self.assertEqual(outcome.confirmation["status"], "confirmed")
        self.assertEqual(outcome.metadata.result_type, "排名")
        self.assertEqual(outcome.metadata.semantic.comparison, "absolute_change")
        self.assertEqual([row[0] for row in outcome.rows], ["江苏省B市农商行", "江苏省A市农商行", "江苏省C市农商行"])
        self.assertIn("最终采用条件", outcome.summary)
        self.assertNotIn("江苏省B市农商行", outcome.sql)

    def test_missing_time_multi_metric_and_unrecognized_states(self):
        missing = self._ask("哪家银行各项存款余额最高？")
        multi = self._ask("各项存款余额和各项贷款余额哪个增长最好？")
        unknown = self._ask("帮我看看经营情况")
        missing_fields = {item["key"]: item for item in missing.confirmation["fields"]}
        multi_fields = {item["key"]: item for item in multi.confirmation["fields"]}
        unknown_fields = {item["key"]: item for item in unknown.confirmation["fields"]}
        self.assertEqual(missing_fields["comparison_period"]["state"], "missing")
        self.assertEqual(multi_fields["metric"]["state"], "needs_confirmation")
        self.assertEqual(unknown_fields["metric"]["state"], "unrecognized")
        self.assertEqual(unknown_fields["analysis"]["state"], "unrecognized")
        self.assertEqual(self.executor.calls, 0)

    def test_tampered_token_field_and_candidate_are_rejected_without_query(self):
        pending = self._ask("哪家银行存款增长最好？")
        attempts = (
            {"token": "0" * 64, "selections": {"comparison_period": "full_range"}},
            {"token": pending.confirmation["token"], "selections": {"comparison_period": "made_up"}},
            {"token": pending.confirmation["token"], "selections": {"metric": "ZB999", "comparison_period": "full_range"}},
        )
        for index, confirmation in enumerate(attempts):
            outcome = self.pipeline.run(QueryCommand("哪家银行存款增长最好？", "u", "c", f"t{index}", confirmation))
            self.assertEqual(outcome.error.code, "INVALID_CONFIRMATION")
            self.assertIsNone(outcome.sql)
        self.assertEqual(self.executor.calls, 0)

    def test_api_optional_confirmation_is_backward_compatible(self):
        from app.api.query import get_query_pipeline

        app.dependency_overrides[get_query_pipeline] = lambda: self.pipeline
        client = TestClient(app)
        try:
            pending = client.post("/api/v1/query", json={"question": "哪家银行存款增长最好？", "user_id": "u", "conversation_id": "c"})
            self.assertEqual(pending.status_code, 400)
            body = pending.json()
            self.assertEqual(body["error"]["code"], "CLARIFICATION_REQUIRED")
            self.assertIsNone(body["sql"])
            confirmed = client.post("/api/v1/query", json={"question": body["question"], "user_id": "u", "conversation_id": "c", "confirmation": {"token": body["confirmation"]["token"], "selections": {"comparison_period": "full_range"}}})
            self.assertEqual(confirmed.status_code, 200)
            self.assertEqual(confirmed.json()["confirmation"]["status"], "confirmed")
        finally:
            client.close()

    def _ask(self, question, confirmation=None):
        return self.pipeline.run(QueryCommand(question, "u", "c", "req", confirmation))

    def _create_database(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript("""
                CREATE TABLE institutions (institution_id TEXT PRIMARY KEY, institution_name TEXT NOT NULL);
                CREATE TABLE metrics (metric_id TEXT PRIMARY KEY, metric_name TEXT NOT NULL, metric_definition TEXT NOT NULL, metric_unit TEXT NOT NULL, value_scale INTEGER NOT NULL);
                CREATE TABLE metric_facts (data_date TEXT NOT NULL, metric_id TEXT NOT NULL, institution_id TEXT NOT NULL, metric_value_scaled INTEGER NOT NULL, PRIMARY KEY(data_date, metric_id, institution_id));
            """)
            connection.executemany("INSERT INTO institutions VALUES (?, ?)", [("ORG001", "江苏省A市农商行"), ("ORG002", "江苏省B市农商行"), ("ORG003", "江苏省C市农商行")])
            connection.executemany("INSERT INTO metrics VALUES (?, ?, ?, ?, ?)", [("ZB001", "各项存款余额", "存款", "亿元", 2), ("ZB002", "各项贷款余额", "贷款", "亿元", 2)])
            rows = []
            for institution, start, end in (("ORG001", 1000, 1300), ("ORG002", 1000, 1600), ("ORG003", 1000, 1100)):
                rows.extend([("2025-01-01", "ZB001", institution, start), ("2026-04-30", "ZB001", institution, end)])
            connection.executemany("INSERT INTO metric_facts VALUES (?, ?, ?, ?)", rows)
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
