from __future__ import annotations

import re
import unittest
from dataclasses import replace
from decimal import Decimal

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
)
from app.application.answer_models import (
    AnswerPayload,
    BenchmarkComparisonFacts,
    InstitutionRef,
    MetricRef,
)
from app.application.models import (
    QueryCommand,
    QueryPlanExecutionResult,
    QueryPlanResult,
    QueryPlanValidation,
    QueryResult,
)
from app.application.planned_pipeline import PlannedQueryPipeline


def comparison_facts(
    *,
    target: float = 31.42,
    benchmark: float = 36.96,
    direction: str = "lower_is_better",
    unit: str = "%",
) -> BenchmarkComparisonFacts:
    difference = round(target - benchmark, 2)
    relative = "above" if difference > 0 else "below" if difference < 0 else "equal"
    if difference == 0:
        assessment = "equal"
    elif direction == "lower_is_better":
        assessment = "better" if difference < 0 else "worse"
    else:
        assessment = "better" if difference > 0 else "worse"
    return BenchmarkComparisonFacts(
        subject=InstitutionRef("ORG013", "江苏省盐城市农商行"),
        metric=MetricRef("ZB012", "成本收入比", unit, direction),
        period="2026-02-28",
        target_value=target,
        benchmark_name="全省13家农商行平均值",
        benchmark_value=benchmark,
        difference=difference,
        difference_unit="百分点" if unit == "%" else unit,
        relative_position=relative,
        performance_assessment=assessment,
    )


class DeterministicAnswerComposerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.composer = DeterministicAnswerComposer()

    def test_lower_is_better_target_below_benchmark_is_better(self):
        answer = self.composer.compose("问题", {}, comparison_facts())

        self.assertEqual(answer.answer_type, "benchmark_comparison")
        self.assertIn("低于全省平均水平5.54个百分点", answer.summary)
        self.assertIn("表现相对较好", answer.summary)

    def test_higher_is_better_target_above_benchmark_is_better(self):
        facts = comparison_facts(
            target=42.0,
            benchmark=40.0,
            direction="higher_is_better",
            unit="亿元",
        )
        answer = self.composer.compose("问题", {}, facts)

        self.assertIn("高于全省平均水平2.00亿元", answer.summary)
        self.assertIn("表现相对较好", answer.summary)

    def test_equal_values_have_equal_assessment(self):
        answer = self.composer.compose(
            "问题", {}, comparison_facts(target=36.96, benchmark=36.96)
        )

        self.assertIn("与全省平均水平相同", answer.summary)
        self.assertIn("表现相当", answer.summary)

    def test_percentage_difference_uses_percentage_points(self):
        facts = comparison_facts()
        answer = self.composer.compose("问题", {}, facts)

        self.assertEqual(facts.difference_unit, "百分点")
        self.assertIn("5.54个百分点", answer.summary)

    def test_table_and_chart_preserve_fact_values(self):
        facts = comparison_facts()
        answer = self.composer.compose("问题", {}, facts)

        self.assertEqual(
            answer.table.rows,
            [
                [facts.subject.institution_name, facts.target_value, facts.metric.unit],
                [facts.benchmark_name, facts.benchmark_value, facts.metric.unit],
            ],
        )
        self.assertEqual(
            answer.chart_spec.series[0].values,
            [facts.target_value, facts.benchmark_value],
        )
        self.assertNotIn("第", answer.summary)

    def test_composer_does_not_invent_numeric_facts(self):
        facts = comparison_facts()
        answer = self.composer.compose("问题", {}, facts)

        rendered_numbers = set(re.findall(r"\d+(?:\.\d+)?", answer.summary))
        self.assertEqual(
            rendered_numbers,
            {"2026", "2", "28", "31.42", "13", "36.96", "5.54"},
        )


class FakeFactsDatabase:
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

    def __init__(self) -> None:
        self.values = {
            f"ORG{index:03d}": Decimal("31.42")
            if index == 13
            else Decimal("37.4216666667")
            for index in range(1, 14)
        }

    def execute_query(self, sql, parameters, max_rows=1000):
        institution_id = parameters["institution_id"]
        value = self.values[institution_id]
        return QueryResult(
            columns=self.columns,
            rows=[
                [
                    institution_id,
                    "江苏省盐城市农商行" if institution_id == "ORG013" else institution_id,
                    parameters["data_date"],
                    parameters["metric_id"],
                    "成本收入比",
                    "%",
                    int(value * 100),
                    2,
                ]
            ],
            row_count=1,
            truncated=False,
            duration_ms=0.1,
        )


class BenchmarkFactsExtractionTest(unittest.TestCase):
    def test_executor_exposes_verified_benchmark_comparison_facts(self):
        institution_ids = [f"ORG{index:03d}" for index in range(1, 14)]
        plan = {
            "status": {"code": "executable"},
            "institutions": {
                "targets": [
                    {
                        "institution_id": "ORG013",
                        "institution_name": "江苏省盐城市农商行",
                    }
                ],
                "comparison_population": {
                    "type": "all",
                    "institution_ids": institution_ids,
                },
            },
            "metrics": {
                "requested_metric_ids": ["ZB012"],
                "source_metric_ids": ["ZB012"],
                "concept_ids": [],
            },
            "time": {"mode": "point", "dates": ["2026-02-28"]},
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB012"],
                    "output_ref": "target",
                    "parameters": {
                        "institution_id": "ORG013",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB012"],
                    "output_ref": "province",
                    "parameters": {
                        "institution_ids": institution_ids,
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP010",
                    "input_refs": ["province"],
                    "output_ref": "province_average",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP003",
                    "input_refs": ["target", "province_average"],
                    "output_ref": "difference",
                    "parameters": {},
                },
            ],
            "checks": [],
            "output": {
                "answer_type": "comparison",
                "result_fields": ["difference"],
                "rounding": {"mode": "final_only", "digits": 2},
            },
        }

        result = DeterministicQueryPlanExecutor(FakeFactsDatabase()).execute(plan)
        facts = result.analysis_facts

        self.assertIsNotNone(facts)
        self.assertEqual(facts.subject.institution_id, "ORG013")
        self.assertEqual(facts.metric.metric_id, "ZB012")
        self.assertEqual(facts.metric.performance_direction, "lower_is_better")
        self.assertEqual(facts.period, "2026-02-28")
        self.assertEqual(facts.target_value, 31.42)
        self.assertAlmostEqual(facts.benchmark_value, 36.96, places=2)
        self.assertAlmostEqual(facts.difference, -5.54, places=2)
        self.assertEqual(facts.difference_unit, "百分点")
        self.assertEqual(facts.performance_assessment, "better")


class StaticPlanner:
    def __init__(self, result):
        self.result = result

    def plan(self, question):
        return replace(self.result, question=question)


class StaticExecutor:
    def __init__(self, facts):
        self.facts = facts

    def execute(self, query_plan):
        return QueryPlanExecutionResult(
            columns=["value"],
            rows=[[1]],
            summary="原摘要。",
            analysis_facts=self.facts,
        )


class FailingIfExecuted:
    def execute(self, query_plan):
        raise AssertionError("non-executable plan must not reach execution")


class RecordingComposer:
    def __init__(self):
        self.calls = []

    def compose(self, question, query_plan, facts):
        self.calls.append((question, query_plan, facts))
        return AnswerPayload("benchmark_comparison", "结论", "结构化摘要")


class NoOpAudit:
    def record(self, event):
        return None


class PlannedPipelineAnswerTest(unittest.TestCase):
    @staticmethod
    def plan_result():
        plan = {
            "status": {"code": "executable"},
            "operations": [{"output_ref": "result"}],
        }
        validation = QueryPlanValidation(True, [], True, [], plan)
        return QueryPlanResult(
            success=True,
            question="问题",
            model="fake-model",
            latency_ms=1,
            repair_attempted=False,
            initial_validation=validation,
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=plan,
        )

    def test_pipeline_calls_composer_only_when_facts_exist(self):
        composer = RecordingComposer()
        pipeline = PlannedQueryPipeline(
            StaticPlanner(self.plan_result()),
            StaticExecutor(comparison_facts()),
            NoOpAudit(),
            answer_composer=composer,
        )

        outcome = pipeline.run(QueryCommand("问题", "u", None, "req"))

        self.assertEqual(len(composer.calls), 1)
        self.assertEqual(outcome.answer.summary, "结构化摘要")
        self.assertEqual(outcome.summary, "原摘要。")
        self.assertEqual(outcome.columns, ["value"])
        self.assertEqual(outcome.rows, [[1]])

    def test_pipeline_preserves_legacy_result_without_facts(self):
        composer = RecordingComposer()
        pipeline = PlannedQueryPipeline(
            StaticPlanner(self.plan_result()),
            StaticExecutor(None),
            NoOpAudit(),
            answer_composer=composer,
        )

        outcome = pipeline.run(QueryCommand("问题", "u", None, "req"))

        self.assertEqual(composer.calls, [])
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.summary, "原摘要。")
        self.assertEqual(outcome.rows, [[1]])

    def test_pipeline_does_not_compose_non_executable_plan(self):
        result = self.plan_result()
        plan = dict(result.query_plan)
        plan["status"] = {
            "code": "data_unavailable",
            "reason": "正式数据不支持。",
        }
        validation = QueryPlanValidation(True, [], True, [], plan)
        result = replace(
            result,
            query_plan=plan,
            initial_validation=validation,
        )
        composer = RecordingComposer()
        pipeline = PlannedQueryPipeline(
            StaticPlanner(result),
            FailingIfExecuted(),
            NoOpAudit(),
            answer_composer=composer,
        )

        outcome = pipeline.run(QueryCommand("问题", "u", None, "req"))

        self.assertEqual(outcome.error.code, "DATA_UNAVAILABLE")
        self.assertEqual(composer.calls, [])
        self.assertIsNone(outcome.answer)


if __name__ == "__main__":
    unittest.main()
