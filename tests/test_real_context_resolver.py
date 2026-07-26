import tempfile
import unittest
import json
from pathlib import Path

from app.adapters.context.real_database_resolver import RealDatabaseContextResolver
from app.adapters.generation.real_rule_generator import RealRuleSQLGenerator
from app.application.errors import RuleNotMatchedError
from scripts.data.import_official_workbook import import_workbook
from test_real_import_contract import _workbook
from app.application.models import LLMResponse, QueryCommand
from app.core.settings import Settings


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, request):
        return LLMResponse(self.responses.pop(0), "fake-real-model", 1)


class RealContextResolverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        source = root / "official.xlsx"
        _workbook(source)
        active = import_workbook(source, root / "real", root / "private")
        self.database = Path(active["business_database"])

    def tearDown(self):
        self.temp.cleanup()

    def test_context_exposes_only_three_business_tables(self):
        context = RealDatabaseContextResolver(self.database).resolve("查询指标")
        self.assertEqual(
            context.allowed_tables,
            frozenset({"institutions", "metrics", "metric_facts"}),
        )
        self.assertIn("scaled_value", context.schema_context)
        self.assertIn("M1", context.metric_context)
        self.assertIn("I1", context.institution_context)
        self.assertNotIn("evaluation_questions", context.schema_context)

    def test_real_rule_never_generates_demo_sql(self):
        context = RealDatabaseContextResolver(self.database).resolve("查询有效客户数量")
        with self.assertRaises(RuleNotMatchedError):
            RealRuleSQLGenerator().generate("查询有效客户数量", context)

    def test_real_rule_executes_single_ranking_and_trend_queries(self):
        from app.bootstrap.container import build_pipeline

        pipeline = build_pipeline(
            self.database,
            settings=Settings(data_environment="real", generator_mode="rule"),
        )
        cases = [
            ("查询机构一在2025-01-31的指标一", "单值", "none", 1),
            ("查询2025-01-31指标一机构排名", "排名", "bar", 1),
            ("查询机构一从2025-01-31到2025-01-31的指标一趋势", "趋势", "line", 1),
        ]
        for index, (question, result_type, chart_type, row_count) in enumerate(cases):
            with self.subTest(result_type=result_type):
                outcome = pipeline.run(
                    QueryCommand(question, "test", "conversation", f"real_{index}")
                )
                self.assertIsNone(outcome.error)
                self.assertEqual(len(outcome.rows), row_count)
                self.assertEqual(outcome.metadata.result_type, result_type)
                self.assertEqual(outcome.metadata.chart_type, chart_type)
                self.assertIsNotNone(outcome.metadata.query_duration_ms)
                self.assertNotIn("机构一", outcome.sql)
                self.assertNotIn("2025-01-31", outcome.sql)

    def test_real_pipeline_executes_basic_metric_query_with_fake_llm(self):
        from app.bootstrap.container import build_pipeline

        semantic = {
            "intent": "metric_single_value",
            "business_domain": "operation",
            "metrics": ["M1"],
            "dimensions": ["institution"],
            "filters": {"institution_id": "I1", "data_date": "2025-01-31"},
            "time_range": None,
            "sort": [],
            "limit": None,
            "clarification_required": False,
            "clarification_question": None,
            "confidence": 0.99,
        }
        sql = {
            "sql": "SELECT i.institution_id, i.institution_name, m.metric_id, m.metric_name, f.data_date, scaled_value(f.metric_value_scaled, m.value_scale) AS metric_value, m.metric_unit FROM metric_facts f JOIN institutions i USING(institution_id) JOIN metrics m USING(metric_id) WHERE f.institution_id=:institution_id AND f.metric_id=:metric_id AND f.data_date=:data_date",
            "parameters": {
                "institution_id": "I1",
                "metric_id": "M1",
                "data_date": "2025-01-31",
            },
            "warnings": [],
        }
        pipeline = build_pipeline(
            self.database,
            settings=Settings(data_environment="real", generator_mode="llm"),
            llm_provider=FakeProvider(
                [json.dumps(semantic, ensure_ascii=False), json.dumps(sql)]
            ),
        )
        outcome = pipeline.run(QueryCommand("查询机构一指标一", "test", None, "r1"))
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.rows[0][-2], 12.34)
        self.assertIn("机构一", outcome.summary)
