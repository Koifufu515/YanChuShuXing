import json
import unittest
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
)
from app.adapters.planning.llm_query_planner import LLMQueryPlanner
from app.bootstrap.container import _project_llm_query_planner_context
from app.application.models import (
    AuditEvent,
    LLMResponse,
    QueryCommand,
    QueryPlanExecutionResult,
    QueryPlanResult,
    QueryPlanValidation,
    QueryResult,
)
from app.application.planned_pipeline import PlannedQueryPipeline
from app.application.query_plan_normalization import normalize_query_plan
from app.application.query_plan_validation import validate_business_rules


class FakeDatabaseExecutor:
    columns = [
        "institution_id",
        "institution_name",
        "data_date",
        "metric_id",
        "metric_name",
        "metric_unit",
        "metric_value_scaled",
        "value_scale",
    ]

    def __init__(self, data):
        self.data = data
        self.calls = []

    def execute_query(self, sql, parameters, max_rows=1000):
        self.calls.append((sql, dict(parameters), max_rows))
        metric_id = parameters["metric_id"]
        institution_id = parameters["institution_id"]
        dates = []
        if "data_date" in parameters:
            dates = [parameters["data_date"]]
        elif "start_date" in parameters:
            dates = sorted(
                date_value
                for org, metric, date_value in self.data
                if org == institution_id
                and metric == metric_id
                and parameters["start_date"] <= date_value <= parameters["end_date"]
            )
        else:
            dates = sorted(
                value
                for key, value in parameters.items()
                if key.startswith("date_")
            )
        rows = []
        for date_value in dates:
            payload = self.data.get((institution_id, metric_id, date_value))
            if payload is None:
                continue
            name, metric_name, unit, scaled, scale = payload
            rows.append(
                [
                    institution_id,
                    name,
                    date_value,
                    metric_id,
                    metric_name,
                    unit,
                    scaled,
                    scale,
                ]
            )
        return QueryResult(self.columns, rows, len(rows), False, 0.1)


class FakeLLMProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            text=self.responses.pop(0),
            model="fake-model",
            latency_ms=5,
        )


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event: AuditEvent):
        self.events.append(event)


class StaticPlanner:
    def __init__(self, result):
        self.result = result

    def plan(self, question):
        return replace(self.result, question=question)


class StaticPlanExecutor:
    def execute(self, query_plan):
        return QueryPlanExecutionResult(
            columns=["value"],
            rows=[[1]],
            summary="执行成功。",
            execution_trace=[{"step": 1, "operator_id": "OP001"}],
        )


def base_plan(operations, checks, output=None):
    return {
        "status": {
            "code": "executable",
            "reason": None,
            "clarification_question": None,
        },
        "institutions": {
            "targets": [],
            "comparison_population": {"type": "none", "institution_ids": []},
        },
        "metrics": {
            "requested_metric_ids": ["ZB001"],
            "source_metric_ids": ["ZB001"],
            "concept_ids": [],
        },
        "time": {
            "mode": "point",
            "dates": ["2025-01-01"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        },
        "operations": operations,
        "checks": checks,
        "output": output
        or {
            "answer_type": "single_value",
            "result_fields": ["value"],
            "unit": None,
            "rounding": {"mode": "final_only", "digits": 2},
            "tie_policy": None,
        },
    }


class DeterministicExecutorTest(unittest.TestCase):
    def test_growth_uses_fixed_reads_and_returns_percentage(self):
        data = {
            ("ORG007", "ZB002", "2025-06-30"): (
                "江苏省G市农商行",
                "各项贷款余额",
                "亿元",
                8000,
                2,
            ),
            ("ORG007", "ZB002", "2025-09-30"): (
                "江苏省G市农商行",
                "各项贷款余额",
                "亿元",
                8800,
                2,
            ),
        }
        database = FakeDatabaseExecutor(data)
        executor = DeterministicQueryPlanExecutor(database)
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP021",
                    "input_refs": [],
                    "output_ref": "base_date",
                    "parameters": {
                        "type": "previous_quarter_end",
                        "reference_date": "2025-09-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB002"],
                    "output_ref": "current",
                    "parameters": {
                        "institution_id": "ORG007",
                        "date": "2025-09-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB002"],
                    "output_ref": "base",
                    "parameters": {
                        "institution_id": "ORG007",
                        "date": "2025-06-30",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP007",
                    "input_refs": ["current", "base"],
                    "output_ref": "growth",
                    "parameters": {},
                },
            ],
            checks=[
                {"type": "record_exists", "parameters": {"metric_ids": ["ZB002"]}},
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB002"]},
                },
            ],
            output={
                "answer_type": "comparison",
                "result_fields": ["growth_rate"],
                "unit": "%",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB002"],
            "source_metric_ids": ["ZB002"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(result.columns, ["value", "unit"])
        self.assertEqual(result.rows, [[10.0, "%"]])
        self.assertEqual(len(database.calls), 2)
        self.assertTrue(all("metric_facts" in call[0] for call in database.calls))

    def test_performance_top_n_preserves_boundary_ties(self):
        data = {
            ("ORG001", "ZB013", "2025-12-31"): (
                "江苏省A市农商行", "不良贷款率", "%", 75, 2
            ),
            ("ORG002", "ZB013", "2025-12-31"): (
                "江苏省B市农商行", "不良贷款率", "%", 80, 2
            ),
            ("ORG003", "ZB013", "2025-12-31"): (
                "江苏省C市农商行", "不良贷款率", "%", 80, 2
            ),
            ("ORG004", "ZB013", "2025-12-31"): (
                "江苏省D市农商行", "不良贷款率", "%", 95, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        ids = ["ORG001", "ORG002", "ORG003", "ORG004"]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP012",
                    "input_refs": ["all_values"],
                    "output_ref": "ranked",
                    "parameters": {
                        "metric_id": "ZB013",
                        "performance_direction": "lower_is_better",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "top2",
                    "parameters": {"n": 2, "direction": "top"},
                },
            ],
            checks=[
                {"type": "record_exists", "parameters": {"metric_ids": ["ZB013"]}},
                {
                    "type": "institution_completeness",
                    "parameters": {"institution_ids": ids},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "tie_preservation",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "ranking",
                "result_fields": ["institution_id", "metric_value", "rank"],
                "unit": "%",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": "preserve_all",
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }
        plan["institutions"]["comparison_population"] = {
            "type": "explicit",
            "institution_ids": ids,
        }

        result = executor.execute(plan)

        self.assertEqual(len(result.rows), 3)
        rank_index = result.columns.index("rank")
        self.assertEqual([row[rank_index] for row in result.rows], [1, 2, 2])

    def test_filter_count_and_merge_returns_detail_rows(self):
        data = {
            ("ORG001", "ZB013", "2025-12-31"): (
                "江苏省A市农商行", "不良贷款率", "%", 140, 2
            ),
            ("ORG002", "ZB013", "2025-12-31"): (
                "江苏省B市农商行", "不良贷款率", "%", 160, 2
            ),
            ("ORG003", "ZB013", "2025-12-31"): (
                "江苏省C市农商行", "不良贷款率", "%", 170, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        ids = ["ORG001", "ORG002", "ORG003"]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {"institution_ids": ids, "date": "2025-12-31"},
                },
                {
                    "step": 2,
                    "operator_id": "OP016",
                    "input_refs": ["all_values"],
                    "output_ref": "filtered",
                    "parameters": {
                        "comparison_operator": ">",
                        "threshold": 1.5,
                        "unit": "%",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP017",
                    "input_refs": ["filtered"],
                    "output_ref": "counted",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP019",
                    "input_refs": ["filtered", "counted"],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {"type": "record_exists", "parameters": {"metric_ids": ["ZB013"]}},
                {
                    "type": "institution_completeness",
                    "parameters": {"institution_ids": ids},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["institutions", "count"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(len(result.rows), 2)
        self.assertIn("满足条件的数量为2家", result.summary)


    def test_composite_preserves_maximum_and_minimum_records(self):
        data = {
            ("ORG001", "ZB012", "2025-01-01"): (
                "江苏省A市农商行",
                "成本收入比",
                "%",
                3000,
                2,
            ),
            ("ORG002", "ZB012", "2025-01-01"): (
                "江苏省B市农商行",
                "成本收入比",
                "%",
                3600,
                2,
            ),
        }
        executor = DeterministicQueryPlanExecutor(
            FakeDatabaseExecutor(data)
        )
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB012"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": ["ORG001", "ORG002"],
                        "date": "2025-01-01",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP014",
                    "input_refs": ["all_values"],
                    "output_ref": "maximum",
                    "parameters": {"type": "max"},
                },
                {
                    "step": 3,
                    "operator_id": "OP014",
                    "input_refs": ["all_values"],
                    "output_ref": "minimum",
                    "parameters": {"type": "min"},
                },
                {
                    "step": 4,
                    "operator_id": "OP019",
                    "input_refs": ["maximum", "minimum"],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB012"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB012"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["maximum", "minimum"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB012"],
            "source_metric_ids": ["ZB012"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(result.columns[0], "result")
        label_index = result.columns.index("result")
        value_index = result.columns.index("metric_value")
        self.assertEqual(
            {row[label_index] for row in result.rows},
            {"最高值", "最低值"},
        )
        self.assertEqual(
            {row[value_index] for row in result.rows},
            {30.0, 36.0},
        )
        self.assertIn("最高值", result.summary)
        self.assertIn("最低值", result.summary)
        self.assertIn("36.00%", result.summary)
        self.assertIn("30.00%", result.summary)


    def test_zero_day_count_keeps_day_unit(self):
        data = {
            ("ORG002", "ZB013", "2025-01-01"): (
                "江苏省B市农商行", "不良贷款率", "%", 140, 2
            ),
            ("ORG002", "ZB013", "2025-01-02"): (
                "江苏省B市农商行", "不良贷款率", "%", 145, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(
            FakeDatabaseExecutor(data)
        )
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "daily_values",
                    "parameters": {
                        "institution_id": "ORG002",
                        "dates": ["2025-01-01", "2025-01-02"],
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP016",
                    "input_refs": ["daily_values"],
                    "output_ref": "filtered",
                    "parameters": {
                        "comparison_operator": ">",
                        "threshold": 2,
                        "unit": "%",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP017",
                    "input_refs": ["filtered"],
                    "output_ref": "day_count",
                    "parameters": {
                        "count_by": "date",
                        "unit": "天",
                    },
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "count",
                "result_fields": ["count"],
                "unit": "天",
                "rounding": {"mode": "final_only", "digits": 0},
                "tie_policy": None,
            },
        )
        plan["time"] = {
            "mode": "series",
            "dates": ["2025-01-01", "2025-01-02"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(
            result.columns,
            ["count", "unit", "population_count", "share_percent"],
        )
        self.assertEqual(result.rows, [[0, "天", 2, 0.0]])
        self.assertEqual(
            result.summary,
            "计数结果为0天，占2天的0.00%。",
        )

    def test_trend_composite_deduplicates_raw_series(self):
        data = {
            ("ORG009", "ZB013", "2025-03-31"): (
                "江苏省I市农商行", "不良贷款率", "%", 148, 2
            ),
            ("ORG009", "ZB013", "2025-06-30"): (
                "江苏省I市农商行", "不良贷款率", "%", 152, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(
            FakeDatabaseExecutor(data)
        )
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "series",
                    "parameters": {
                        "institution_id": "ORG009",
                        "dates": ["2025-03-31", "2025-06-30"],
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP018",
                    "input_refs": ["series"],
                    "output_ref": "trend",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP014",
                    "input_refs": ["series"],
                    "output_ref": "maximum",
                    "parameters": {"type": "max"},
                },
                {
                    "step": 4,
                    "operator_id": "OP019",
                    "input_refs": ["series", "trend", "maximum"],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["date", "value", "trend"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["time"] = {
            "mode": "series",
            "dates": ["2025-03-31", "2025-06-30"],
            "start_date": None,
            "end_date": None,
            "grain": "quarter_end",
            "comparison_periods": [],
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        label_index = result.columns.index("result")
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(
            {row[label_index] for row in result.rows},
            {"时间序列与趋势", "最高值"},
        )
        self.assertIn("趋势判断：持续上升", result.summary)
        self.assertIn("最高值", result.summary)

    def test_composite_differences_preserve_base_current_and_change(self):
        data = {
            ("ORG001", "ZB001", "2025-01-01"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 3792, 2
            ),
            ("ORG001", "ZB001", "2025-12-31"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 3887, 2
            ),
            ("ORG001", "ZB010", "2025-01-01"): (
                "江苏省A市农商行", "净利润", "万元", 7607, 2
            ),
            ("ORG001", "ZB010", "2025-12-31"): (
                "江苏省A市农商行", "净利润", "万元", 7545, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(
            FakeDatabaseExecutor(data)
        )
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "deposit_current",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "deposit_base",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-01-01",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB010"],
                    "output_ref": "profit_current",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP001",
                    "input_refs": ["ZB010"],
                    "output_ref": "profit_base",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-01-01",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP003",
                    "input_refs": ["deposit_current", "deposit_base"],
                    "output_ref": "deposit_change",
                    "parameters": {},
                },
                {
                    "step": 6,
                    "operator_id": "OP003",
                    "input_refs": ["profit_current", "profit_base"],
                    "output_ref": "profit_change",
                    "parameters": {},
                },
                {
                    "step": 7,
                    "operator_id": "OP019",
                    "input_refs": ["deposit_change", "profit_change"],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB001", "ZB010"]},
                },
                {
                    "type": "metric_completeness",
                    "parameters": {"metric_ids": ["ZB001", "ZB010"]},
                },
                {
                    "type": "unit_consistency",
                    "parameters": {"metric_ids": ["ZB001", "ZB010"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["deposit_change", "profit_change"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["time"] = {
            "mode": "comparison",
            "dates": [],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [
                {
                    "type": "explicit",
                    "date": "2025-01-01",
                    "start_date": None,
                    "end_date": None,
                },
                {
                    "type": "explicit",
                    "date": "2025-12-31",
                    "start_date": None,
                    "end_date": None,
                },
            ],
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB001", "ZB010"],
            "source_metric_ids": ["ZB001", "ZB010"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(
            result.columns,
            [
                "result",
                "metric_name",
                "base_date",
                "base_value",
                "current_date",
                "current_value",
                "change",
                "direction",
                "unit",
            ],
        )
        self.assertEqual(len(result.rows), 2)
        self.assertIn(
            "各项存款余额：37.92亿元→38.87亿元，增加0.95亿元",
            result.summary,
        )
        self.assertIn(
            "净利润：76.07万元→75.45万元，减少0.62万元",
            result.summary,
        )



class BatchFailureRegressionTest(unittest.TestCase):
    def test_numeric_sort_accepts_multiple_read_inputs(self):
        data = {
            ("ORG001", "ZB001", "2025-12-31"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 1000, 2
            ),
            ("ORG005", "ZB001", "2025-12-31"): (
                "江苏省E市农商行", "各项存款余额", "亿元", 3000, 2
            ),
            ("ORG009", "ZB001", "2025-12-31"): (
                "江苏省I市农商行", "各项存款余额", "亿元", 2000, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        operations = []
        for step, institution_id in enumerate(
            ["ORG001", "ORG005", "ORG009"],
            start=1,
        ):
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": f"value_{step}",
                    "parameters": {
                        "institution_id": institution_id,
                        "date": "2025-12-31",
                    },
                }
            )
        operations.append(
            {
                "step": 4,
                "operator_id": "OP011",
                "input_refs": ["value_1", "value_2", "value_3"],
                "output_ref": "ranked",
                "parameters": {"order": "descending"},
            }
        )
        plan = base_plan(
            operations=operations,
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB001"]},
                }
            ],
            output={
                "answer_type": "ranking",
                "result_fields": ["institution_name", "metric_value", "rank"],
                "unit": "亿元",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )

        result = executor.execute(plan)

        value_index = result.columns.index("metric_value")
        self.assertEqual(
            [row[value_index] for row in result.rows],
            [30.0, 20.0, 10.0],
        )

    def test_dynamic_province_average_broadcasts_to_each_institution(self):
        data = {
            ("ORG001", "ZB013", "2025-12-31"): (
                "江苏省A市农商行", "不良贷款率", "%", 100, 2
            ),
            ("ORG002", "ZB013", "2025-12-31"): (
                "江苏省B市农商行", "不良贷款率", "%", 200, 2
            ),
            ("ORG003", "ZB013", "2025-12-31"): (
                "江苏省C市农商行", "不良贷款率", "%", 300, 2
            ),
        }
        ids = ["ORG001", "ORG002", "ORG003"]
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP010",
                    "input_refs": ["all_values"],
                    "output_ref": "province_average",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP003",
                    "input_refs": ["all_values", "province_average"],
                    "output_ref": "differences",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP016",
                    "input_refs": ["differences"],
                    "output_ref": "above_average",
                    "parameters": {
                        "comparison_operator": ">",
                        "threshold": 0,
                        "unit": "%",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP017",
                    "input_refs": ["above_average"],
                    "output_ref": "institution_count",
                    "parameters": {
                        "count_by": "institution",
                        "unit": "家",
                    },
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "count",
                "result_fields": ["count"],
                "unit": "家",
                "rounding": {"mode": "final_only", "digits": 0},
                "tie_policy": None,
            },
        )
        plan["institutions"]["comparison_population"] = {
            "type": "explicit",
            "institution_ids": ids,
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(result.rows, [[1, "家"]])

    def test_cross_period_growth_aligns_by_institution_and_metric(self):
        data = {
            ("ORG001", "ZB001", "2024-12-31"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 1000, 2
            ),
            ("ORG002", "ZB001", "2024-12-31"): (
                "江苏省B市农商行", "各项存款余额", "亿元", 2000, 2
            ),
            ("ORG001", "ZB001", "2026-03-31"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 1200, 2
            ),
            ("ORG002", "ZB001", "2026-03-31"): (
                "江苏省B市农商行", "各项存款余额", "亿元", 2600, 2
            ),
        }
        ids = ["ORG001", "ORG002"]
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "current_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "base_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2024-12-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP007",
                    "input_refs": ["current_values", "base_values"],
                    "output_ref": "growth_values",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP011",
                    "input_refs": ["growth_values"],
                    "output_ref": "ranked",
                    "parameters": {"order": "descending"},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB001"]},
                },
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB001"]},
                },
            ],
            output={
                "answer_type": "ranking",
                "result_fields": ["institution_name", "metric_value", "rank"],
                "unit": "%",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["time"] = {
            "mode": "comparison",
            "dates": ["2026-03-31"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [
                {
                    "type": "explicit",
                    "date": "2024-12-31",
                    "start_date": None,
                    "end_date": None,
                }
            ],
        }

        result = executor.execute(plan)

        value_index = result.columns.index("metric_value")
        self.assertEqual(
            [row[value_index] for row in result.rows],
            [30.0, 20.0],
        )

    def test_branch_average_deposit_uses_plain_quotient(self):
        data = {
            ("ORG005", "ZB001", "2026-02-28"): (
                "江苏省E市农商行", "各项存款余额", "亿元", 100, 2
            ),
            ("ORG005", "ZB019", "2026-02-28"): (
                "江苏省E市农商行", "网点数量", "个", 5, 0
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "deposit_balance",
                    "parameters": {
                        "institution_id": "ORG005",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB019"],
                    "output_ref": "branch_count",
                    "parameters": {
                        "institution_id": "ORG005",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP020",
                    "input_refs": ["deposit_balance"],
                    "output_ref": "deposit_wanyuan",
                    "parameters": {
                        "from_unit": "亿元",
                        "to_unit": "万元",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP006",
                    "input_refs": ["deposit_wanyuan", "branch_count"],
                    "output_ref": "branch_average",
                    "parameters": {
                        "numerator": "deposit_wanyuan",
                        "denominator": "branch_count",
                        "multiplier": 1,
                        "result_unit": "万元/网点",
                    },
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB001", "ZB019"]},
                },
                {
                    "type": "metric_completeness",
                    "parameters": {"metric_ids": ["ZB001", "ZB019"]},
                },
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB019"]},
                },
            ],
            output={
                "answer_type": "single_value",
                "result_fields": ["value"],
                "unit": "万元/网点",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB030"],
            "source_metric_ids": ["ZB001", "ZB019"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertEqual(result.rows, [[2000.0, "万元/网点"]])

    def test_metric_completeness_allows_metrics_read_at_different_dates(self):
        data = {
            ("ORG001", "ZB001", "2025-12-31"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 1000, 2
            ),
            ("ORG001", "ZB019", "2026-01-31"): (
                "江苏省A市农商行", "网点数量", "个", 5, 0
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "deposit",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB019"],
                    "output_ref": "branches",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2026-01-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP019",
                    "input_refs": ["deposit", "branches"],
                    "output_ref": "combined",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "metric_completeness",
                    "parameters": {"metric_ids": ["ZB001", "ZB019"]},
                }
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["deposit", "branches"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB001", "ZB019"],
            "source_metric_ids": ["ZB001", "ZB019"],
            "concept_ids": [],
        }

        result = executor.execute(plan)

        self.assertTrue(result.rows)

    def test_frozen_business_concept_rejects_partial_execution(self):
        project_root = Path(__file__).resolve().parents[1]
        context = json.loads(
            (
                project_root
                / "config"
                / "query_planner"
                / "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB011"],
                    "output_ref": "profit",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2026-04-30",
                    },
                }
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB011"]},
                }
            ],
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB011"],
            "source_metric_ids": ["ZB011"],
            "concept_ids": [],
        }

        errors = validate_business_rules(
            plan,
            context,
            "评估该机构的盈利能力，包含净利润和成本收入比。",
        )

        self.assertTrue(
            any(
                error["path"] == "metrics.requested_metric_ids"
                and "ZB012" in error["message"]
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                error["path"] == "metrics.concept_ids"
                and "BC006" in error["message"]
                for error in errors
            ),
            errors,
        )


class QueryPlanContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[1]
        config_dir = project_root / "config" / "query_planner"
        cls.schema = json.loads(
            (config_dir / "query_plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.context = json.loads(
            (config_dir / "query_planner_context.json").read_text(
                encoding="utf-8"
            )
        )

    def test_schema_rejects_op014_alias_and_multiple_inputs(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "first",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-03-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "second",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-06-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP014",
                    "input_refs": ["first", "second"],
                    "output_ref": "maximum",
                    "parameters": {"type": "maximum"},
                },
            ],
            checks=[],
        )
        errors = list(
            Draft202012Validator(self.schema).iter_errors(plan)
        )

        self.assertTrue(errors)
        messages = " ".join(error.message for error in errors)
        self.assertIn("too long", messages)
        self.assertIn("maximum", messages)

    def test_series_change_and_extreme_requires_one_series_read_and_merge(self):
        dates = [
            "2025-03-31",
            "2025-06-30",
            "2025-09-30",
            "2025-12-31",
            "2026-03-31",
        ]
        operations = []
        refs = []
        for step, date_value in enumerate(dates, start=1):
            output_ref = f"value_{step}"
            refs.append(output_ref)
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": output_ref,
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": date_value,
                    },
                }
            )
        operations.append(
            {
                "step": 6,
                "operator_id": "OP014",
                "input_refs": refs,
                "output_ref": "maximum",
                "parameters": {"type": "max"},
            }
        )
        plan = base_plan(
            operations=operations,
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["series", "trend", "maximum"],
                "unit": "%",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "series",
            "dates": dates,
            "start_date": None,
            "end_date": None,
            "grain": "quarter_end",
            "comparison_periods": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "请分析江苏省I市农商行的不良贷款率逐季变化，"
            "各季度末数值是多少？哪个季度数值最高？",
        )
        messages = " ".join(error["message"] for error in errors)

        self.assertIn("OP014必须严格接收一个", messages)
        self.assertIn("parameters.dates", messages)
        self.assertIn("OP018", messages)
        self.assertIn("OP019", messages)

    def test_both_extremes_require_two_op014_and_final_merge(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB012"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": [
                            f"ORG{index:03d}"
                            for index in range(1, 14)
                        ],
                        "start_date": "2025-01-01",
                        "end_date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP014",
                    "input_refs": ["all_values"],
                    "output_ref": "maximum",
                    "parameters": {"type": "max"},
                },
                {
                    "step": 3,
                    "operator_id": "OP014",
                    "input_refs": ["all_values"],
                    "output_ref": "minimum",
                    "parameters": {"type": "min"},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB012"]},
                },
                {
                    "type": "institution_completeness",
                    "parameters": {
                        "institution_ids": [
                            f"ORG{index:03d}"
                            for index in range(1, 14)
                        ]
                    },
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB012"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB012"]},
                },
            ],
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB012"],
            "source_metric_ids": ["ZB012"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "range",
            "dates": [],
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "grain": "day",
            "comparison_periods": [],
        }
        plan["institutions"]["comparison_population"] = {
            "type": "all_official_institutions",
            "institution_ids": [
                f"ORG{index:03d}" for index in range(1, 14)
            ],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "2025年全年，成本收入比的单日最高值出现在哪家？"
            "单日最低值在哪家？",
        )
        messages = " ".join(error["message"] for error in errors)

        self.assertIn("OP019", messages)

    def test_single_scalar_extreme_requires_matching_op014(self):
        ids = [
            f"ORG{index:03d}"
            for index in range(1, 14)
        ]

        def make_plan(operations):
            plan = base_plan(
                operations=operations,
                checks=[
                    {
                        "type": "record_exists",
                        "parameters": {
                            "metric_ids": ["ZB013"],
                        },
                    },
                    {
                        "type": "institution_completeness",
                        "parameters": {
                            "institution_ids": ids,
                        },
                    },
                    {
                        "type": "unrounded_comparison",
                        "parameters": {
                            "metric_ids": ["ZB013"],
                        },
                    },
                ],
            )
            plan["metrics"] = {
                "requested_metric_ids": ["ZB013"],
                "source_metric_ids": ["ZB013"],
                "concept_ids": [],
            }
            plan["institutions"]["comparison_population"] = {
                "type": "all_official_institutions",
                "institution_ids": ids,
            }
            return plan

        cases = {
            "ranking_chain_without_op014": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP012",
                    "input_refs": ["all_values"],
                    "output_ref": "ranked",
                    "parameters": {
                        "metric_id": "ZB013",
                        "performance_direction": "lower_is_better",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "first",
                    "parameters": {
                        "n": 1,
                        "direction": "top",
                    },
                },
            ],
            "op014_with_wrong_direction": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP014",
                    "input_refs": ["all_values"],
                    "output_ref": "maximum",
                    "parameters": {
                        "type": "max",
                    },
                },
            ],
        }

        for name, operations in cases.items():
            with self.subTest(name=name):
                errors = validate_business_rules(
                    make_plan(operations),
                    self.context,
                    "13家农商行中不良贷款率最低的是哪家？",
                )
                messages = " ".join(
                    error["message"]
                    for error in errors
                )

                self.assertIn(
                    "必须使用OP014，且parameters.type=min",
                    messages,
                )

    def test_numeric_top_n_is_not_scalar_extreme(self):
        ids = [
            f"ORG{index:03d}"
            for index in range(1, 14)
        ]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP011",
                    "input_refs": ["all_values"],
                    "output_ref": "ascending_values",
                    "parameters": {
                        "order": "ascending",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP013",
                    "input_refs": ["ascending_values"],
                    "output_ref": "lowest_three",
                    "parameters": {
                        "n": 3,
                        "direction": "top",
                    },
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                },
                {
                    "type": "institution_completeness",
                    "parameters": {
                        "institution_ids": ids,
                    },
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                },
                {
                    "type": "tie_preservation",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                },
            ],
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }
        plan["institutions"]["comparison_population"] = {
            "type": "all_official_institutions",
            "institution_ids": ids,
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "13家农商行中不良贷款率数值最低3家是哪些？",
        )
        messages = " ".join(
            error["message"]
            for error in errors
        )

        self.assertNotIn(
            "题目询问单一最低或最小值",
            messages,
        )

    def test_dynamic_province_average_filter_requires_difference_step(self):
        ids = [f"ORG{index:03d}" for index in range(1, 14)]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "target_daily",
                    "parameters": {
                        "institution_id": "ORG002",
                        "start_date": "2025-01-01",
                        "end_date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "province_daily",
                    "parameters": {
                        "institution_ids": ids,
                        "start_date": "2025-01-01",
                        "end_date": "2025-12-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP010",
                    "input_refs": ["province_daily"],
                    "output_ref": "province_average",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP016",
                    "input_refs": [
                        "target_daily",
                        "province_average",
                    ],
                    "output_ref": "filtered",
                    "parameters": {
                        "comparison_operator": ">",
                        "threshold": 0,
                        "unit": "%",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP017",
                    "input_refs": ["filtered"],
                    "output_ref": "counted",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "institution_completeness",
                    "parameters": {"institution_ids": ids},
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "range",
            "dates": [],
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "grain": "day",
            "comparison_periods": [],
        }
        plan["institutions"]["comparison_population"] = {
            "type": "all_official_institutions",
            "institution_ids": ids,
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "2025年全年，江苏省B市农商行的不良贷款率"
            "有多少天高于全省均值？",
        )
        messages = " ".join(error["message"] for error in errors)

        self.assertIn("OP016只能接收一个", messages)
        self.assertIn("OP003", messages)
        self.assertIn("差值序列", messages)


    def test_trend_merge_rejects_redundant_raw_series(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "series",
                    "parameters": {
                        "institution_id": "ORG009",
                        "dates": ["2025-03-31", "2025-06-30"],
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP018",
                    "input_refs": ["series"],
                    "output_ref": "trend",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP014",
                    "input_refs": ["series"],
                    "output_ref": "maximum",
                    "parameters": {"type": "max"},
                },
                {
                    "step": 4,
                    "operator_id": "OP019",
                    "input_refs": ["series", "trend", "maximum"],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "date_completeness",
                    "parameters": {
                        "dates": ["2025-03-31", "2025-06-30"]
                    },
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["series", "trend", "maximum"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["time"] = {
            "mode": "series",
            "dates": ["2025-03-31", "2025-06-30"],
            "start_date": None,
            "end_date": None,
            "grain": "quarter_end",
            "comparison_periods": [],
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "请分析逐季变化并说明哪个季度最高。",
        )

        self.assertTrue(
            any(
                "OP018结果已经包含原始时间序列" in error["message"]
                for error in errors
            )
        )



class DerivedMetricLanguageRuleTest(
    unittest.TestCase
):
    def setUp(self):
        root = Path(
            __file__
        ).resolve().parents[1]

        self.context = json.loads(
            (
                root
                / "config/query_planner/"
                "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )

    def ratio_plan(
        self,
        *,
        requested_metric_id,
        numerator_metric_id,
        denominator_metric_id,
        institution_id,
        date_value,
    ):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": [
                        numerator_metric_id
                    ],
                    "output_ref": "numerator",
                    "parameters": {
                        "institution_id": (
                            institution_id
                        ),
                        "date": date_value,
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": [
                        denominator_metric_id
                    ],
                    "output_ref": "denominator",
                    "parameters": {
                        "institution_id": (
                            institution_id
                        ),
                        "date": date_value,
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP006",
                    "input_refs": [
                        "numerator",
                        "denominator",
                    ],
                    "output_ref": "ratio",
                    "parameters": {
                        "numerator": "numerator",
                        "denominator": "denominator",
                        "multiplier": 100,
                        "result_unit": "%",
                    },
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": [
                            numerator_metric_id,
                            denominator_metric_id,
                        ],
                    },
                },
                {
                    "type": "metric_completeness",
                    "parameters": {
                        "metric_ids": [
                            numerator_metric_id,
                            denominator_metric_id,
                        ],
                    },
                },
                {
                    "type": "denominator_nonzero",
                    "parameters": {
                        "metric_ids": [
                            denominator_metric_id
                        ],
                    },
                },
                {
                    "type": "unit_consistency",
                    "parameters": {
                        "metric_ids": [
                            numerator_metric_id,
                            denominator_metric_id,
                        ],
                    },
                },
            ],
            output={
                "answer_type": "single_value",
                "result_fields": [
                    "metric_value",
                    "unit",
                ],
                "unit": "%",
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": None,
            },
        )

        plan["institutions"]["targets"] = [
            {
                "institution_id": (
                    institution_id
                ),
                "role": "target",
            }
        ]

        plan["metrics"] = {
            "requested_metric_ids": [
                requested_metric_id
            ],
            "source_metric_ids": [
                numerator_metric_id,
                denominator_metric_id,
            ],
            "concept_ids": [],
        }

        plan["time"] = {
            "mode": "point",
            "dates": [date_value],
            "start_date": None,
            "end_date": None,
            "grain": "month_end",
            "comparison_periods": [],
        }

        return plan

    def test_corporate_loan_ratio_phrase_is_one_metric(
        self,
    ):
        plan = self.ratio_plan(
            requested_metric_id="ZB026",
            numerator_metric_id="ZB005",
            denominator_metric_id="ZB002",
            institution_id="ORG003",
            date_value="2025-09-30",
        )

        errors = validate_business_rules(
            plan,
            self.context,
            (
                "江苏省C市农商行2025年9月末，"
                "对公贷款占各项贷款的比例是多少？"
            ),
        )

        self.assertEqual(errors, [])

    def test_formula_parenthetical_is_explanation(
        self,
    ):
        plan = self.ratio_plan(
            requested_metric_id="ZB023",
            numerator_metric_id="ZB011",
            denominator_metric_id="ZB009",
            institution_id="ORG007",
            date_value="2026-01-31",
        )

        errors = validate_business_rules(
            plan,
            self.context,
            (
                "江苏省G市农商行2026年1月底，"
                "净利润率（净利润除以营业收入）"
                "是多少？"
            ),
        )

        self.assertEqual(errors, [])

    def test_defined_npl_ratio_cannot_only_clarify(
        self,
    ):
        plan = base_plan(
            operations=[],
            checks=[],
        )

        plan["status"] = {
            "code": "clarification_required",
            "reason": "缺少评价标准。",
            "clarification_question": (
                "请提供比较标准。"
            ),
        }

        plan["institutions"]["targets"] = [
            {
                "institution_id": "ORG011",
                "role": "target",
            }
        ]

        plan["metrics"] = {
            "requested_metric_ids": [
                "ZB013"
            ],
            "source_metric_ids": [],
            "concept_ids": [],
        }

        plan["time"] = {
            "mode": "point",
            "dates": ["2025-12-31"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            (
                "江苏省K市农商行2025年12月31日，"
                "不良贷款余额占贷款总额的比重大不大？"
            ),
        )

        messages = " ".join(
            error["message"]
            for error in errors
        )

        self.assertIn(
            "不得仅因“大不大”要求澄清",
            messages,
        )

    def test_defined_npl_ratio_executes_as_zb013(
        self,
    ):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_ratio",
                    "parameters": {
                        "institution_id": "ORG011",
                        "date": "2025-12-31",
                    },
                }
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                }
            ],
            output={
                "answer_type": "single_value",
                "result_fields": [
                    "metric_value",
                ],
                "unit": "%",
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": None,
            },
        )

        plan["institutions"]["targets"] = [
            {
                "institution_id": "ORG011",
                "role": "target",
            }
        ]

        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }

        plan["time"] = {
            "mode": "point",
            "dates": ["2025-12-31"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            (
                "江苏省K市农商行2025年12月31日，"
                "不良贷款余额占贷款总额的比重大不大？"
            ),
        )

        self.assertEqual(errors, [])

class QueryPlannerComponentTest(unittest.TestCase):
    def test_invalid_first_plan_is_repaired_once(self):
        schema = {
            "type": "object",
            "required": ["status", "operations", "checks"],
            "properties": {
                "status": {"type": "object"},
                "operations": {"type": "array"},
                "checks": {"type": "array"},
            },
        }
        context = {
            "data_range": {
                "start_date": "2024-12-31",
                "end_date": "2026-04-30",
            }
        }
        invalid = {"status": {"code": "pending_project_definition"}, "operations": []}
        valid = {
            "status": {"code": "pending_project_definition"},
            "operations": [],
            "checks": [],
        }
        provider = FakeLLMProvider([json.dumps(invalid), json.dumps(valid)])
        planner = LLMQueryPlanner(provider, "prompt", schema, context, 20)

        result = planner.plan("测试问题")

        self.assertTrue(result.success)
        self.assertTrue(result.repair_attempted)
        self.assertEqual(len(provider.requests), 2)


class PlannedPipelineTest(unittest.TestCase):
    def _result(self, status_code="executable"):
        plan = base_plan([], [])
        plan["status"] = {
            "code": status_code,
            "reason": "口径尚未确认" if status_code != "executable" else None,
            "clarification_question": None,
        }
        validation = QueryPlanValidation(True, [], True, [], plan)
        return QueryPlanResult(
            success=True,
            question="原问题",
            model="fake-model",
            latency_ms=5,
            repair_attempted=False,
            initial_validation=validation,
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=plan,
        )

    def test_success_keeps_existing_api_outcome_contract_and_adds_metadata(self):
        audit = RecordingAudit()
        pipeline = PlannedQueryPipeline(
            StaticPlanner(self._result()),
            StaticPlanExecutor(),
            audit,
        )

        outcome = pipeline.run(QueryCommand("问题", "u", None, "req"))

        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.rows, [[1]])
        self.assertIsNone(outcome.sql)
        self.assertEqual(outcome.metadata.route, "QueryPlan")
        self.assertEqual(outcome.metadata.execution_trace[0]["operator_id"], "OP001")
        self.assertEqual(
            [event.event_type for event in audit.events],
            ["request_started", "query_succeeded"],
        )

    def test_pending_definition_returns_structured_error_without_execution(self):
        audit = RecordingAudit()
        pipeline = PlannedQueryPipeline(
            StaticPlanner(self._result("pending_project_definition")),
            StaticPlanExecutor(),
            audit,
        )

        outcome = pipeline.run(QueryCommand("问题", "u", None, "req"))

        self.assertEqual(outcome.error.code, "PENDING_PROJECT_DEFINITION")
        self.assertEqual(outcome.metadata.failure_reason, "pending_project_definition")
        self.assertEqual(audit.events[-1].event_type, "query_failed")


class RemainingFailureRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[1]
        config_dir = project_root / "config" / "query_planner"
        cls.schema = json.loads(
            (config_dir / "query_plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.context = json.loads(
            (config_dir / "query_planner_context.json").read_text(
                encoding="utf-8"
            )
        )

    def test_explicit_metric_name_does_not_trigger_broad_pending_concept(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "deposit",
                    "parameters": {
                        "institution_id": "ORG005",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB019"],
                    "output_ref": "branches",
                    "parameters": {
                        "institution_id": "ORG005",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP020",
                    "input_refs": ["deposit"],
                    "output_ref": "deposit_wan",
                    "parameters": {
                        "from_unit": "亿元",
                        "to_unit": "万元",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP006",
                    "input_refs": ["deposit_wan", "branches"],
                    "output_ref": "branch_average",
                    "parameters": {
                        "numerator": "deposit_wan",
                        "denominator": "branches",
                        "multiplier": 1,
                        "result_unit": "万元/网点",
                    },
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": ["ZB001", "ZB019"],
                    },
                },
                {
                    "type": "metric_completeness",
                    "parameters": {
                        "metric_ids": ["ZB001", "ZB019"],
                    },
                },
                {
                    "type": "denominator_nonzero",
                    "parameters": {
                        "metric_ids": ["ZB019"],
                    },
                },
            ],
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB030"],
            "source_metric_ids": ["ZB001", "ZB019"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2026-02-28"]

        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省E市农商行在2026-02-28的网点平均存款规模（万元/网点）是多少？",
        )

        self.assertFalse(
            any(error["path"] == "status.code" for error in errors),
            errors,
        )

    def test_period_average_ranking_does_not_require_op010(self):
        all_orgs = [f"ORG{index:03d}" for index in range(1, 14)]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "all_deposits",
                    "parameters": {
                        "institution_ids": all_orgs,
                        "start_date": "2025-01-01",
                        "end_date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP009",
                    "input_refs": ["all_deposits"],
                    "output_ref": "institution_averages",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP011",
                    "input_refs": ["institution_averages"],
                    "output_ref": "sorted_averages",
                    "parameters": {"order": "descending"},
                },
                {
                    "step": 4,
                    "operator_id": "OP013",
                    "input_refs": ["sorted_averages"],
                    "output_ref": "top3",
                    "parameters": {"n": 3, "direction": "top"},
                },
                {
                    "step": 5,
                    "operator_id": "OP013",
                    "input_refs": ["sorted_averages"],
                    "output_ref": "bottom3",
                    "parameters": {"n": 3, "direction": "bottom"},
                },
                {
                    "step": 6,
                    "operator_id": "OP019",
                    "input_refs": ["top3", "bottom3"],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "institution_completeness",
                    "parameters": {"metric_ids": ["ZB001"]},
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB001"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB001"]},
                },
                {
                    "type": "tie_preservation",
                    "parameters": {"metric_ids": ["ZB001"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["top3", "bottom3"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": "preserve_all",
            },
        )
        plan["institutions"] = {
            "targets": [
                {"institution_id": org, "role": "target"}
                for org in all_orgs
            ],
            "comparison_population": {
                "type": "all_official_institutions",
                "institution_ids": all_orgs,
            },
        }
        plan["time"] = {
            "mode": "range",
            "dates": [],
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "grain": "day",
            "comparison_periods": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "2025年全年，各项存款余额的均值排名前三和后三的分别是哪几家？",
        )

        self.assertFalse(
            any("OP010" in error["message"] for error in errors),
            errors,
        )

    def test_schema_requires_empty_op021_input_refs(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP021",
                    "input_refs": ["ZB001"],
                    "output_ref": "previous_month",
                    "parameters": {
                        "type": "previous_month_end",
                        "reference_date": "2026-04-30",
                    },
                }
            ],
            checks=[],
        )

        errors = list(Draft202012Validator(self.schema).iter_errors(plan))

        self.assertTrue(
            any(
                list(error.absolute_path)[-1:] == ["input_refs"]
                for error in errors
            ),
            errors,
        )

    def test_month_and_year_comparison_requires_current_value_in_final_merge(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP021",
                    "input_refs": [],
                    "output_ref": "previous_month",
                    "parameters": {
                        "type": "previous_month_end",
                        "reference_date": "2026-04-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP021",
                    "input_refs": [],
                    "output_ref": "previous_year",
                    "parameters": {
                        "type": "previous_year_same_period",
                        "reference_date": "2026-04-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "current_value",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2026-04-30",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "previous_month_value",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "previous_year_value",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-04-30",
                    },
                },
                {
                    "step": 6,
                    "operator_id": "OP007",
                    "input_refs": ["current_value", "previous_month_value"],
                    "output_ref": "mom_change",
                    "parameters": {},
                },
                {
                    "step": 7,
                    "operator_id": "OP007",
                    "input_refs": ["current_value", "previous_year_value"],
                    "output_ref": "yoy_change",
                    "parameters": {},
                },
                {
                    "step": 8,
                    "operator_id": "OP019",
                    "input_refs": ["mom_change", "yoy_change"],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB001"]},
                }
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["mom_change", "yoy_change"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["time"] = {
            "mode": "comparison",
            "dates": ["2026-04-30"],
            "start_date": None,
            "end_date": None,
            "grain": "month_end",
            "comparison_periods": [
                {
                    "type": "explicit",
                    "date": "2026-04-30",
                    "start_date": None,
                    "end_date": None,
                },
                {
                    "type": "previous_month_end",
                    "date": "2026-03-31",
                    "start_date": None,
                    "end_date": None,
                },
                {
                    "type": "previous_year_same_period",
                    "date": "2025-04-30",
                    "start_date": None,
                    "end_date": None,
                },
            ],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "分析江苏省A市农商行在2026-04-30的各项存款余额环比和同比变化情况。",
        )

        self.assertTrue(
            any("本期原始值" in error["message"] for error in errors),
            errors,
        )

        plan["operations"][-1]["input_refs"] = [
            "current_value",
            "mom_change",
            "yoy_change",
        ]
        plan["output"]["result_fields"] = [
            "current_value",
            "mom_change",
            "yoy_change",
        ]
        errors = validate_business_rules(
            plan,
            self.context,
            "分析江苏省A市农商银行2026-04-30各项存款余额，环比和同比分别变化了多少，同时给出当前值。",
        )

        self.assertEqual(errors, [])

    def test_mixed_current_value_and_growth_results_are_all_rendered(self):
        data = {
            ("ORG001", "ZB001", "2026-04-30"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 4170, 2
            ),
            ("ORG001", "ZB001", "2026-03-31"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 4232, 2
            ),
            ("ORG001", "ZB001", "2025-04-30"): (
                "江苏省A市农商行", "各项存款余额", "亿元", 4205, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "current_value",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2026-04-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "previous_month_value",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "previous_year_value",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-04-30",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP007",
                    "input_refs": ["current_value", "previous_month_value"],
                    "output_ref": "mom_change",
                    "parameters": {},
                },
                {
                    "step": 5,
                    "operator_id": "OP007",
                    "input_refs": ["current_value", "previous_year_value"],
                    "output_ref": "yoy_change",
                    "parameters": {},
                },
                {
                    "step": 6,
                    "operator_id": "OP019",
                    "input_refs": [
                        "current_value",
                        "mom_change",
                        "yoy_change",
                    ],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB001"]},
                }
            ],
            output={
                "answer_type": "composite",
                "result_fields": [
                    "current_value",
                    "mom_change",
                    "yoy_change",
                ],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )

        result = executor.execute(plan)

        self.assertEqual(
            [row[0] for row in result.rows],
            ["current_value", "mom_change", "yoy_change"],
        )
        self.assertIn("当前值为41.70亿元", result.summary)
        self.assertIn("环比下降1.47%", result.summary)
        self.assertIn("同比下降0.83%", result.summary)


class FinalBaselineRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        project_root = Path(__file__).resolve().parents[1]
        cls.context = json.loads(
            (
                project_root
                / "config"
                / "query_planner"
                / "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )

    def test_deposit_scale_alias_is_not_pending_concept(self):
        plan = base_plan([], [])
        plan["status"] = {
            "code": "pending_project_definition",
            "reason": "规模待确认",
            "clarification_question": None,
        }
        plan["operations"] = []
        plan["checks"] = []
        plan["metrics"] = {
            "requested_metric_ids": [],
            "source_metric_ids": [],
            "concept_ids": ["BC004"],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "2025年12月31日，13家农商行中谁的存款规模排第一？",
        )

        self.assertTrue(
            any(
                error["path"] == "status.code"
                and "明确别名" in error["message"]
                for error in errors
            ),
            errors,
        )

    def test_daily_deposit_average_must_read_zb001_and_use_op009(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB031"],
                    "output_ref": "daily_average_source",
                    "parameters": {
                        "institution_id": "ORG013",
                        "start_date": "2025-01-01",
                        "end_date": "2025-03-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP009",
                    "input_refs": ["daily_average_source"],
                    "output_ref": "daily_average",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB031"]},
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB031"]},
                },
            ],
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB031"],
            "source_metric_ids": ["ZB031"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "range",
            "dates": [],
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
            "grain": "day",
            "comparison_periods": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省M市农商行2025年一季度的日均存款余额是多少？",
        )
        messages = " ".join(error["message"] for error in errors)

        self.assertIn("ZB001", messages)
        self.assertIn("不得直接读取ZB031", messages)

    def test_last_numeric_rank_requires_descending_then_bottom(self):
        all_orgs = [f"ORG{index:03d}" for index in range(1, 14)]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB011"],
                    "output_ref": "all_profit",
                    "parameters": {
                        "institution_ids": all_orgs,
                        "date": "2025-08-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP011",
                    "input_refs": ["all_profit"],
                    "output_ref": "ranked",
                    "parameters": {"order": "ascending"},
                },
                {
                    "step": 3,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "last_one",
                    "parameters": {"n": 1, "direction": "bottom"},
                },
            ],
            checks=[
                {
                    "type": "institution_completeness",
                    "parameters": {"metric_ids": ["ZB011"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB011"]},
                },
                {
                    "type": "tie_preservation",
                    "parameters": {"metric_ids": ["ZB011"]},
                },
            ],
            output={
                "answer_type": "ranking",
                "result_fields": ["institution_name", "metric_value", "rank"],
                "unit": "万元",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": "preserve_all",
            },
        )
        plan["institutions"] = {
            "targets": [],
            "comparison_population": {
                "type": "all_official_institutions",
                "institution_ids": all_orgs,
            },
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB011"],
            "source_metric_ids": ["ZB011"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2025-08-31"]

        errors = validate_business_rules(
            plan,
            self.context,
            "2025年8月末，全省净利润按数值排名最后一名的是哪家？",
        )

        self.assertTrue(
            any("OP011.order必须为descending" in error["message"] for error in errors),
            errors,
        )

    def test_customer_components_and_total_are_all_rendered(self):
        data = {
            ("ORG005", "ZB021", "2025-12-31"): (
                "江苏省E市农商行", "对公客户数", "户", 1461, 0
            ),
            ("ORG005", "ZB020", "2025-12-31"): (
                "江苏省E市农商行", "个人客户数", "户", 146477, 0
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB021"],
                    "output_ref": "corp_customers",
                    "parameters": {
                        "institution_id": "ORG005",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB020"],
                    "output_ref": "personal_customers",
                    "parameters": {
                        "institution_id": "ORG005",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP002",
                    "input_refs": ["corp_customers", "personal_customers"],
                    "output_ref": "total_customers",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP019",
                    "input_refs": [
                        "corp_customers",
                        "personal_customers",
                        "total_customers",
                    ],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB021", "ZB020"]},
                },
                {
                    "type": "metric_completeness",
                    "parameters": {"metric_ids": ["ZB021", "ZB020"]},
                },
                {
                    "type": "unit_consistency",
                    "parameters": {"metric_ids": ["ZB021", "ZB020"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": [
                    "corp_customers",
                    "personal_customers",
                    "total_customers",
                ],
                "unit": "户",
                "rounding": {"mode": "final_only", "digits": 0},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB021", "ZB020", "ZB028"],
            "source_metric_ids": ["ZB021", "ZB020"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2025-12-31"]

        result = executor.execute(plan)

        self.assertEqual(len(result.rows), 3)
        self.assertIn("对公客户数为1461户", result.summary)
        self.assertIn("个人客户数为146477户", result.summary)
        self.assertIn("合计客户数为147938户", result.summary)

    def test_two_ratios_are_both_rendered(self):
        data = {
            ("ORG007", "ZB005", "2026-03-31"): (
                "江苏省G市农商行", "对公贷款余额", "亿元", 5354, 2
            ),
            ("ORG007", "ZB006", "2026-03-31"): (
                "江苏省G市农商行", "个人贷款余额", "亿元", 4646, 2
            ),
            ("ORG007", "ZB002", "2026-03-31"): (
                "江苏省G市农商行", "各项贷款余额", "亿元", 10000, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB005"],
                    "output_ref": "corporate_loan",
                    "parameters": {
                        "institution_id": "ORG007",
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB006"],
                    "output_ref": "personal_loan",
                    "parameters": {
                        "institution_id": "ORG007",
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB002"],
                    "output_ref": "total_loan",
                    "parameters": {
                        "institution_id": "ORG007",
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP006",
                    "input_refs": ["corporate_loan", "total_loan"],
                    "output_ref": "corporate_loan_ratio",
                    "parameters": {
                        "numerator": "corporate_loan",
                        "denominator": "total_loan",
                        "multiplier": 100,
                        "result_unit": "%",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP006",
                    "input_refs": ["personal_loan", "total_loan"],
                    "output_ref": "personal_loan_ratio",
                    "parameters": {
                        "numerator": "personal_loan",
                        "denominator": "total_loan",
                        "multiplier": 100,
                        "result_unit": "%",
                    },
                },
                {
                    "step": 6,
                    "operator_id": "OP019",
                    "input_refs": [
                        "personal_loan_ratio",
                        "corporate_loan_ratio",
                    ],
                    "output_ref": "final",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB002"]},
                }
            ],
            output={
                "answer_type": "composite",
                "result_fields": [
                    "personal_loan_ratio",
                    "corporate_loan_ratio",
                ],
                "unit": "%",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB026", "ZB027"],
            "source_metric_ids": ["ZB005", "ZB006", "ZB002"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2026-03-31"]

        result = executor.execute(plan)

        self.assertEqual(len(result.rows), 2)
        self.assertIn("个人贷款占比为46.46%", result.summary)
        self.assertIn("对公贷款占比为53.54%", result.summary)

    def test_absolute_yoy_change_uses_difference_and_renders_direction(self):
        data = {
            ("ORG013", "ZB011", "2025-01-31"): (
                "江苏省M市农商行", "净利润", "万元", 16091, 2
            ),
            ("ORG013", "ZB011", "2026-01-31"): (
                "江苏省M市农商行", "净利润", "万元", 18450, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP021",
                    "input_refs": [],
                    "output_ref": "base_date",
                    "parameters": {
                        "type": "previous_year_same_period",
                        "reference_date": "2026-01-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB011"],
                    "output_ref": "current_value",
                    "parameters": {
                        "institution_id": "ORG013",
                        "date": "2026-01-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB011"],
                    "output_ref": "base_value",
                    "parameters": {
                        "institution_id": "ORG013",
                        "date": "2025-01-31",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP003",
                    "input_refs": ["current_value", "base_value"],
                    "output_ref": "absolute_change",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB011"]},
                }
            ],
            output={
                "answer_type": "comparison",
                "result_fields": ["absolute_change"],
                "unit": "万元",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB011"],
            "source_metric_ids": ["ZB011"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "comparison",
            "dates": [],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [
                {
                    "type": "explicit",
                    "date": "2026-01-31",
                    "start_date": None,
                    "end_date": None,
                },
                {
                    "type": "previous_year_same_period",
                    "date": "2025-01-31",
                    "start_date": None,
                    "end_date": None,
                },
            ],
        }

        result = executor.execute(plan)

        self.assertIn("增加23.59万元", result.summary)
        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省M市农商行的净利润在2026-01-31，同比（较去年同期）变动了多少？",
        )
        self.assertFalse(
            any("绝对差额" in error["message"] for error in errors),
            errors,
        )

    def test_multiple_explicit_metrics_require_final_merge(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_rate",
                    "parameters": {
                        "institution_id": "ORG004",
                        "date": "2025-10-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB015"],
                    "output_ref": "provision_coverage",
                    "parameters": {
                        "institution_id": "ORG004",
                        "date": "2025-10-31",
                    },
                },
            ],
            checks=[
                {
                    "type": "metric_completeness",
                    "parameters": {"metric_ids": ["ZB013", "ZB015"]},
                }
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["npl_rate", "provision_coverage"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013", "ZB015"],
            "source_metric_ids": ["ZB013", "ZB015"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2025-10-31"]

        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省D市农商行在2025-10-31的不良贷款率和拨备覆盖率分别是多少？",
        )

        self.assertTrue(
            any("必须以OP019合并" in error["message"] for error in errors),
            errors,
        )

    def test_target_daily_comparison_requires_separate_target_read(self):
        all_orgs = [f"ORG{index:03d}" for index in range(1, 14)]
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_daily_values",
                    "parameters": {
                        "institution_ids": all_orgs,
                        "start_date": "2025-01-01",
                        "end_date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP010",
                    "input_refs": ["all_daily_values"],
                    "output_ref": "province_daily_average",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP003",
                    "input_refs": ["all_daily_values", "province_daily_average"],
                    "output_ref": "difference",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP016",
                    "input_refs": ["difference"],
                    "output_ref": "selected_days",
                    "parameters": {
                        "comparison_operator": ">",
                        "threshold": 0,
                        "unit": "%",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP017",
                    "input_refs": ["selected_days"],
                    "output_ref": "day_count",
                    "parameters": {"count_by": "date", "unit": "天"},
                },
            ],
            checks=[
                {
                    "type": "institution_completeness",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "count",
                "result_fields": ["count"],
                "unit": "天",
                "rounding": {"mode": "final_only", "digits": 0},
                "tie_policy": None,
            },
        )
        plan["institutions"] = {
            "targets": [{"institution_id": "ORG002", "role": "target"}],
            "comparison_population": {
                "type": "all_official_institutions",
                "institution_ids": all_orgs,
            },
        }
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "range",
            "dates": [],
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "grain": "day",
            "comparison_periods": [],
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "2025年全年，江苏省B市农商行的不良贷款率有多少天高于全省均值？",
        )

        self.assertTrue(
            any("单独读取目标机构日序列" in error["message"] for error in errors),
            errors,
        )

    def test_date_count_includes_population_share(self):
        data = {
            ("ORG002", "ZB013", "2025-01-01"): (
                "江苏省B市农商行", "不良贷款率", "%", 100, 2
            ),
            ("ORG002", "ZB013", "2025-01-02"): (
                "江苏省B市农商行", "不良贷款率", "%", -100, 2
            ),
            ("ORG002", "ZB013", "2025-01-03"): (
                "江苏省B市农商行", "不良贷款率", "%", 100, 2
            ),
        }
        executor = DeterministicQueryPlanExecutor(FakeDatabaseExecutor(data))
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "daily_difference",
                    "parameters": {
                        "institution_id": "ORG002",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-03",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP016",
                    "input_refs": ["daily_difference"],
                    "output_ref": "positive_days",
                    "parameters": {
                        "comparison_operator": ">",
                        "threshold": 0,
                        "unit": "%",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP017",
                    "input_refs": ["positive_days"],
                    "output_ref": "day_count",
                    "parameters": {"count_by": "date", "unit": "天"},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
                {
                    "type": "date_completeness",
                    "parameters": {"metric_ids": ["ZB013"]},
                },
            ],
            output={
                "answer_type": "count",
                "result_fields": ["count", "share_percent"],
                "unit": "天",
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013"],
            "source_metric_ids": ["ZB013"],
            "concept_ids": [],
        }
        plan["time"] = {
            "mode": "range",
            "dates": [],
            "start_date": "2025-01-01",
            "end_date": "2025-01-03",
            "grain": "day",
            "comparison_periods": [],
        }

        result = executor.execute(plan)

        self.assertEqual(result.rows, [[2, "天", 3, 66.67]])
        self.assertIn("占3天的66.67%", result.summary)


    def test_direct_stored_metrics_accept_direct_reads_and_merge(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_rate",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB015"],
                    "output_ref": "provision_coverage",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP019",
                    "input_refs": ["npl_rate", "provision_coverage"],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "record_exists",
                    "parameters": {"metric_ids": ["ZB013", "ZB015"]},
                },
                {
                    "type": "metric_completeness",
                    "parameters": {"metric_ids": ["ZB013", "ZB015"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["不良贷款率", "拨备覆盖率"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013", "ZB015"],
            "source_metric_ids": ["ZB013", "ZB015"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2025-11-30"]

        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省I市农商行在2025-11-30的不良贷款率和拨备覆盖率分别是多少？",
        )

        self.assertFalse(
            any(
                "直接询问正式基础指标" in error["message"]
                or "source_metric_ids必须与全部OP001" in error["message"]
                or "不得合并重新计算" in error["message"]
                for error in errors
            ),
            errors,
        )

    def test_direct_stored_metrics_reject_recalculated_substitutes(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_rate_raw",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB014"],
                    "output_ref": "npl_balance",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP001",
                    "input_refs": ["ZB015"],
                    "output_ref": "coverage_raw",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP001",
                    "input_refs": ["ZB002"],
                    "output_ref": "loan_balance",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP006",
                    "input_refs": ["npl_balance", "loan_balance"],
                    "output_ref": "npl_rate_calc",
                    "parameters": {
                        "numerator": "npl_balance",
                        "denominator": "loan_balance",
                        "multiplier": 100,
                        "result_unit": "%",
                    },
                },
                {
                    "step": 6,
                    "operator_id": "OP006",
                    "input_refs": ["coverage_raw", "npl_balance"],
                    "output_ref": "coverage_calc",
                    "parameters": {
                        "numerator": "coverage_raw",
                        "denominator": "npl_balance",
                        "multiplier": 100,
                        "result_unit": "%",
                    },
                },
                {
                    "step": 7,
                    "operator_id": "OP019",
                    "input_refs": ["npl_rate_calc", "coverage_calc"],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "metric_completeness",
                    "parameters": {
                        "metric_ids": ["ZB013", "ZB014", "ZB015", "ZB002"]
                    },
                },
                {
                    "type": "denominator_nonzero",
                    "parameters": {"metric_ids": ["ZB014", "ZB002"]},
                },
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["不良贷款率", "拨备覆盖率"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013", "ZB015"],
            "source_metric_ids": ["ZB013", "ZB014", "ZB015", "ZB002"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2025-11-30"]

        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省I市农商行在2025-11-30的不良贷款率和拨备覆盖率分别是多少？",
        )

        self.assertTrue(
            any(
                "source_metric_ids必须只包含" in error["message"]
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                "不得合并重新计算" in error["message"]
                for error in errors
            ),
            errors,
        )

    def test_source_metrics_must_match_actual_op001_reads(self):
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_rate",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB015"],
                    "output_ref": "coverage",
                    "parameters": {
                        "institution_id": "ORG001",
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP019",
                    "input_refs": ["npl_rate", "coverage"],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            checks=[
                {
                    "type": "metric_completeness",
                    "parameters": {
                        "metric_ids": ["ZB013", "ZB014", "ZB015", "ZB002"]
                    },
                }
            ],
            output={
                "answer_type": "composite",
                "result_fields": ["不良贷款率", "拨备覆盖率"],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": None,
            },
        )
        plan["metrics"] = {
            "requested_metric_ids": ["ZB013", "ZB015"],
            "source_metric_ids": ["ZB013", "ZB014", "ZB015", "ZB002"],
            "concept_ids": [],
        }
        plan["time"]["dates"] = ["2025-12-31"]

        errors = validate_business_rules(
            plan,
            self.context,
            "江苏省A市农商行在2025-12-31的不良贷款率和拨备覆盖率分别是多少？",
        )

        self.assertTrue(
            any(
                "source_metric_ids必须与全部OP001实际读取" in error["message"]
                for error in errors
            ),
            errors,
        )


class QueryPlannerRuntimeContextTest(unittest.TestCase):
    def test_removes_language_rules_without_mutating_full_context(self):
        context = {
            "metrics": [
                {
                    "metric_id": "ZB001",
                    "name": "各项存款余额",
                }
            ],
            "language_rules": [
                {
                    "rule_id": "LR001",
                    "expression": "A比B多多少",
                }
            ],
        }

        llm_context = _project_llm_query_planner_context(context)

        self.assertIsNot(llm_context, context)
        self.assertNotIn("language_rules", llm_context)
        self.assertIn("language_rules", context)
        self.assertEqual(llm_context["metrics"], context["metrics"])


class QueryPlanMetricCompletenessNormalizationTest(unittest.TestCase):
    def test_adds_missing_check_for_multiple_source_metrics(self):
        plan = {
            "status": {"code": "executable"},
            "metrics": {
                "requested_metric_ids": ["ZB013", "ZB015"],
                "source_metric_ids": ["ZB013", "ZB015"],
                "concept_ids": [],
            },
            "checks": [
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": ["ZB013", "ZB015"],
                    },
                }
            ],
        }

        normalized = normalize_query_plan(plan)

        self.assertEqual(
            normalized["checks"][-1],
            {
                "type": "metric_completeness",
                "parameters": {
                    "metric_ids": ["ZB013", "ZB015"],
                },
            },
        )
        self.assertFalse(
            any(
                check.get("type") == "metric_completeness"
                for check in plan["checks"]
            )
        )
        self.assertEqual(
            normalize_query_plan(normalized),
            normalized,
        )

    def test_preserves_existing_metric_completeness_check(self):
        existing_check = {
            "type": "metric_completeness",
            "parameters": {
                "metric_ids": ["ZB015", "ZB013"],
            },
        }
        plan = {
            "status": {"code": "executable"},
            "metrics": {
                "requested_metric_ids": ["ZB013", "ZB015"],
                "source_metric_ids": ["ZB013", "ZB015"],
                "concept_ids": [],
            },
            "checks": [existing_check],
        }

        normalized = normalize_query_plan(plan)

        self.assertEqual(
            normalized["checks"],
            [existing_check],
        )

    def test_skips_single_metric_and_non_executable_plans(self):
        cases = [
            (
                "single_metric",
                "executable",
                ["ZB013"],
            ),
            (
                "non_executable",
                "clarification_required",
                ["ZB013", "ZB015"],
            ),
        ]

        for name, status_code, source_metric_ids in cases:
            with self.subTest(name=name):
                plan = {
                    "status": {"code": status_code},
                    "metrics": {
                        "requested_metric_ids": source_metric_ids,
                        "source_metric_ids": source_metric_ids,
                        "concept_ids": [],
                    },
                    "checks": [],
                }

                normalized = normalize_query_plan(plan)

                self.assertEqual(normalized["checks"], [])


class QueryPlanScalarExtremeNormalizationTest(
    unittest.TestCase
):
    @staticmethod
    def _ranking_plan():
        return {
            "status": {
                "code": "executable",
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "all_values",
                    "parameters": {
                        "institution_ids": [
                            "ORG001",
                            "ORG002",
                        ],
                        "date": "2025-12-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP012",
                    "input_refs": ["all_values"],
                    "output_ref": "ranked",
                    "parameters": {
                        "metric_id": "ZB013",
                        "performance_direction":
                            "lower_is_better",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "lowest_npl",
                    "parameters": {
                        "n": 1,
                        "direction": "top",
                    },
                },
            ],
            "checks": [
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                },
                {
                    "type": "tie_preservation",
                    "parameters": {
                        "metric_ids": ["ZB013"],
                    },
                },
            ],
            "output": {
                "answer_type": "ranking",
                "result_fields": [
                    "institution_id",
                    "metric_value",
                    "rank",
                ],
                "unit": "%",
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": "preserve_all",
            },
        }

    def test_converts_single_institution_extreme_chain(self):
        original = self._ranking_plan()

        normalized = normalize_query_plan(
            original,
            question=(
                "13家农商行中，2025年12月31日"
                "不良贷款率最低的是哪家？"
            ),
        )

        self.assertEqual(
            [
                operation["operator_id"]
                for operation in normalized["operations"]
            ],
            ["OP001", "OP014"],
        )
        self.assertEqual(
            normalized["operations"][-1],
            {
                "step": 2,
                "operator_id": "OP014",
                "input_refs": ["all_values"],
                "output_ref": "lowest_npl",
                "parameters": {
                    "type": "min",
                },
            },
        )
        self.assertEqual(
            normalized["output"]["answer_type"],
            "extreme_value",
        )
        self.assertEqual(
            normalized["output"]["result_fields"],
            ["institution_id", "metric_value"],
        )
        self.assertIsNone(
            normalized["output"]["tie_policy"]
        )
        self.assertFalse(
            any(
                check.get("type")
                == "tie_preservation"
                for check in normalized["checks"]
            )
        )
        self.assertEqual(
            [
                operation["operator_id"]
                for operation in original["operations"]
            ],
            ["OP001", "OP012", "OP013"],
        )
        self.assertEqual(
            normalize_query_plan(
                normalized,
                question=(
                    "13家农商行中，2025年12月31日"
                    "不良贷款率最低的是哪家？"
                ),
            ),
            normalized,
        )

    def test_preserves_ranking_top_n_and_threshold_language(
        self,
    ):
        questions = [
            "不良贷款率排名第一的是哪家？",
            "不良贷款率数值最低3家是哪些？",
            "不良贷款率最低监管要求是多少？",
        ]

        for question in questions:
            with self.subTest(question=question):
                plan = self._ranking_plan()
                normalized = normalize_query_plan(
                    plan,
                    question=question,
                )

                self.assertEqual(
                    [
                        operation["operator_id"]
                        for operation
                        in normalized["operations"]
                    ],
                    ["OP001", "OP012", "OP013"],
                )


if __name__ == "__main__":
    unittest.main()
