import json
import unittest
from dataclasses import replace

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
)
from app.adapters.planning.llm_query_planner import LLMQueryPlanner
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


class SequencePlanner:
    def __init__(self, results):
        self.results = list(results)
        self.questions = []

    def plan(self, question):
        self.questions.append(question)
        return replace(self.results.pop(0), question=question)


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
        self.assertIn("共2条结果", result.summary)


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
            "clarification_question": "请确认指标和时间。" if status_code == "clarification_required" else None,
            "questions": [
                {
                    "field": "metric",
                    "label": "您想查询哪项指标？",
                    "reason": "贷款情况没有说明具体指标。",
                    "type": "single_select",
                    "options": [
                        {"value": "ZB002", "label": "各项贷款余额"}
                    ],
                    "required": True,
                },
                {
                    "field": "date",
                    "label": "您想查询哪个日期？",
                    "reason": "原问题没有提供时间。",
                    "type": "date",
                    "options": [],
                    "required": True,
                },
            ] if status_code == "clarification_required" else [],
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

    def test_structured_clarification_is_replanned_after_valid_answers(self):
        audit = RecordingAudit()
        planner = SequencePlanner(
            [self._result("clarification_required"), self._result("executable")]
        )
        pipeline = PlannedQueryPipeline(planner, StaticPlanExecutor(), audit)
        original_question = "帮我看看江苏省A市农商行的贷款情况。"
        first = pipeline.run(QueryCommand(original_question, "u", "conv", "req1"))

        self.assertEqual(first.error.code, "CLARIFICATION_REQUIRED")
        self.assertEqual(first.confirmation["status"], "clarification_required")
        self.assertEqual(
            [item["field"] for item in first.confirmation["questions"]],
            ["metric", "date"],
        )
        self.assertTrue(
            all(item["field"] != "growth_method" for item in first.confirmation["questions"])
        )

        second = pipeline.run(
            QueryCommand(
                original_question,
                "u",
                "conv",
                "req2",
                clarification_id=first.confirmation["clarification_id"],
                clarification_answers={"metric": "ZB002", "date": "2025-12-31"},
            )
        )

        self.assertIsNone(second.error)
        self.assertEqual(second.rows, [[1]])
        self.assertEqual(len(planner.questions), 2)
        self.assertIn('\"field\":\"metric\"', planner.questions[1])
        self.assertIn('\"value\":\"ZB002\"', planner.questions[1])

    def test_forged_clarification_option_is_rejected_before_replanning(self):
        planner = SequencePlanner([self._result("clarification_required")])
        pipeline = PlannedQueryPipeline(planner, StaticPlanExecutor(), RecordingAudit())
        first = pipeline.run(QueryCommand("问题", "u", "conv", "req1"))
        rejected = pipeline.run(
            QueryCommand(
                "问题",
                "u",
                "conv",
                "req2",
                clarification_id=first.confirmation["clarification_id"],
                clarification_answers={"metric": "ZB999", "date": "2025-12-31"},
            )
        )
        self.assertEqual(rejected.error.code, "INVALID_CONFIRMATION")
        self.assertEqual(len(planner.questions), 1)


if __name__ == "__main__":
    unittest.main()
