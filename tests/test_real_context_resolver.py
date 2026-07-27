import tempfile
import unittest
from pathlib import Path

from app.adapters.context.real_database_resolver import RealDatabaseContextResolver
from app.adapters.generation.real_rule_generator import RealRuleSQLGenerator
from app.application.errors import RuleNotMatchedError
from app.application.models import (
    QueryCommand,
    QueryPlanResult,
    QueryPlanValidation,
)
from app.core.settings import Settings
from scripts.data.import_official_workbook import import_workbook
from test_real_import_contract import _workbook


class StaticQueryPlanner:
    def __init__(self, query_plan):
        self.query_plan = query_plan

    def plan(self, question: str) -> QueryPlanResult:
        validation = QueryPlanValidation(
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=self.query_plan,
        )
        return QueryPlanResult(
            success=True,
            question=question,
            model="fake-query-planner",
            latency_ms=1.0,
            repair_attempted=False,
            initial_validation=validation,
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=self.query_plan,
        )


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

    def test_real_pipeline_executes_basic_metric_query_with_fake_planner(self):
        from app.bootstrap.container import build_pipeline

        query_plan = {
            "status": {
                "code": "executable",
                "reason": "测试固定查询计划。",
                "clarification_question": None,
            },
            "institutions": {
                "target_institution_ids": ["I1"],
                "comparison_population": {
                    "type": "selected_institutions",
                    "institution_ids": ["I1"],
                },
            },
            "metrics": {
                "requested_metric_ids": ["M1"],
                "source_metric_ids": ["M1"],
            },
            "time": {
                "mode": "point",
                "grain": "day",
                "dates": ["2025-01-31"],
                "start_date": None,
                "end_date": None,
                "comparison_periods": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["M1"],
                    "output_ref": "metric_value",
                    "parameters": {
                        "institution_id": "I1",
                        "date": "2025-01-31",
                    },
                }
            ],
            "checks": [],
            "output": {
                "format": "table",
                "result_fields": [],
                "rounding": {
                    "mode": "half_up",
                    "digits": 2,
                },
                "tie_policy": None,
            },
        }

        pipeline = build_pipeline(
            self.database,
            settings=Settings(data_environment="real", generator_mode="llm"),
            query_planner=StaticQueryPlanner(query_plan),
        )

        outcome = pipeline.run(
            QueryCommand("查询机构一指标一", "test", None, "r1")
        )

        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.rows[0][-2], 12.34)
        self.assertIn("机构一", outcome.summary)
        self.assertEqual(outcome.metadata.route, "QueryPlan")
        self.assertEqual(
            [item["operator_id"] for item in outcome.metadata.execution_trace],
            ["OP001"],
        )


if __name__ == "__main__":
    unittest.main()
