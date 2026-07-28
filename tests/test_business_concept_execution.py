import json
import unittest
from pathlib import Path

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
)
from app.application.query_plan_validation import validate_business_rules
from app.application.models import QueryResult


class FakeDatabase:
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

    def __init__(self, values):
        self.values = values

    def execute_query(self, sql, parameters, max_rows=1000):
        key = (
            parameters["institution_id"],
            parameters["metric_id"],
            parameters["data_date"],
        )
        payload = self.values.get(key)
        rows = []
        if payload is not None:
            institution_name, metric_name, unit, scaled, scale = payload
            rows.append(
                [
                    key[0],
                    institution_name,
                    key[2],
                    key[1],
                    metric_name,
                    unit,
                    scaled,
                    scale,
                ]
            )
        return QueryResult(
            columns=self.columns,
            rows=rows,
            row_count=len(rows),
            truncated=False,
            duration_ms=0.1,
        )


def plan_base(operations, output_fields):
    return {
        "status": {
            "code": "executable",
            "reason": None,
            "clarification_question": None,
        },
        "institutions": {
            "targets": [
                {
                    "institution_id": "ORG002",
                    "role": "target",
                }
            ],
            "comparison_population": {
                "type": "explicit",
                "institution_ids": ["ORG001", "ORG002"],
            },
        },
        "metrics": {
            "requested_metric_ids": ["ZB001", "ZB002", "ZB022"],
            "source_metric_ids": ["ZB001", "ZB002"],
            "concept_ids": ["BC004"],
        },
        "time": {
            "mode": "point",
            "dates": ["2026-04-30"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        },
        "operations": operations,
        "checks": [
            {
                "type": "metric_completeness",
                "parameters": {
                    "metric_ids": ["ZB001", "ZB002"],
                },
            },
            {
                "type": "denominator_nonzero",
                "parameters": {
                    "metric_ids": ["ZB001"],
                },
            },
        ],
        "output": {
            "answer_type": "composite",
            "result_fields": output_fields,
            "unit": None,
            "rounding": {
                "mode": "final_only",
                "digits": 2,
            },
            "tie_policy": "preserve_all",
        },
    }


class BusinessConceptExecutionTest(unittest.TestCase):
    def setUp(self):
        self.values = {
            ("ORG001", "ZB001", "2026-04-30"): (
                "甲银行", "各项存款余额", "亿元", 10000, 2
            ),
            ("ORG002", "ZB001", "2026-04-30"): (
                "乙银行", "各项存款余额", "亿元", 8000, 2
            ),
            ("ORG001", "ZB002", "2026-04-30"): (
                "甲银行", "各项贷款余额", "亿元", 8000, 2
            ),
            ("ORG002", "ZB002", "2026-04-30"): (
                "乙银行", "各项贷款余额", "亿元", 7200, 2
            ),
        }

    def test_op006_aligns_different_metrics_by_institution_and_date(self):
        operations = [
            {
                "step": 1,
                "operator_id": "OP001",
                "input_refs": ["ZB002"],
                "output_ref": "loans",
                "parameters": {
                    "institution_ids": ["ORG001", "ORG002"],
                    "date": "2026-04-30",
                },
            },
            {
                "step": 2,
                "operator_id": "OP001",
                "input_refs": ["ZB001"],
                "output_ref": "deposits",
                "parameters": {
                    "institution_ids": ["ORG001", "ORG002"],
                    "date": "2026-04-30",
                },
            },
            {
                "step": 3,
                "operator_id": "OP006",
                "input_refs": ["loans", "deposits"],
                "output_ref": "ldr",
                "parameters": {
                    "numerator": "ZB002",
                    "denominator": "ZB001",
                    "multiplier": 100,
                    "result_unit": "%",
                },
            },
            {
                "step": 4,
                "operator_id": "OP011",
                "input_refs": ["ldr"],
                "output_ref": "ldr_rank",
                "parameters": {"order": "descending"},
            },
        ]
        plan = plan_base(operations, ["存贷比排名"])
        executor = DeterministicQueryPlanExecutor(
            FakeDatabase(self.values)
        )

        result = executor.execute(plan)

        self.assertEqual(len(result.rows), 1)
        self.assertIn("ZB022", result.rows[0])
        self.assertIn(90.0, result.rows[0])
        self.assertIn(1, result.rows[0])

    def test_composite_preserves_scalar_ratio_with_rank_records(self):
        operations = [
            {
                "step": 1,
                "operator_id": "OP001",
                "input_refs": ["ZB001"],
                "output_ref": "deposit_all",
                "parameters": {
                    "institution_ids": ["ORG001", "ORG002"],
                    "date": "2026-04-30",
                },
            },
            {
                "step": 2,
                "operator_id": "OP011",
                "input_refs": ["deposit_all"],
                "output_ref": "deposit_rank",
                "parameters": {"order": "descending"},
            },
            {
                "step": 3,
                "operator_id": "OP001",
                "input_refs": ["ZB002"],
                "output_ref": "loan_target",
                "parameters": {
                    "institution_id": "ORG002",
                    "date": "2026-04-30",
                },
            },
            {
                "step": 4,
                "operator_id": "OP001",
                "input_refs": ["ZB001"],
                "output_ref": "deposit_target",
                "parameters": {
                    "institution_id": "ORG002",
                    "date": "2026-04-30",
                },
            },
            {
                "step": 5,
                "operator_id": "OP006",
                "input_refs": ["loan_target", "deposit_target"],
                "output_ref": "ldr_value",
                "parameters": {
                    "numerator": "ZB002",
                    "denominator": "ZB001",
                    "multiplier": 100,
                    "result_unit": "%",
                },
            },
            {
                "step": 6,
                "operator_id": "OP019",
                "input_refs": ["ldr_value", "deposit_rank"],
                "output_ref": "final_result",
                "parameters": {},
            },
        ]
        plan = plan_base(
            operations,
            ["存贷比", "各项存款余额排名"],
        )
        executor = DeterministicQueryPlanExecutor(
            FakeDatabase(self.values)
        )

        result = executor.execute(plan)

        rendered = json.dumps(
            result.rows,
            ensure_ascii=False,
        )
        self.assertIn("存贷比", rendered)
        self.assertIn("90.0", rendered)
        self.assertIn("乙银行", rendered)
        self.assertNotIn("甲银行", rendered)


class BusinessConceptValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.context = json.loads(
            (
                root
                / "config"
                / "query_planner"
                / "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )

    def test_main_metrics_requires_deposit_and_loan_classification(self):
        plan = {
            "status": {
                "code": "executable",
                "reason": None,
                "clarification_question": None,
            },
            "institutions": {
                "targets": [],
                "comparison_population": {
                    "type": "all_official_institutions",
                    "institution_ids": [
                        f"ORG{index:03d}"
                        for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB001", "ZB002", "ZB022", "ZB013",
                    "ZB015", "ZB016", "ZB017", "ZB011",
                    "ZB012",
                ],
                "source_metric_ids": [
                    "ZB001", "ZB002", "ZB013", "ZB015",
                    "ZB016", "ZB017", "ZB011", "ZB012",
                ],
                "concept_ids": ["BC001", "BC002", "BC003"],
            },
            "time": {
                "mode": "point",
                "dates": ["2026-01-31"],
                "start_date": None,
                "end_date": None,
                "grain": "day",
                "comparison_periods": [],
            },
            "operations": [],
            "checks": [],
            "output": {
                "answer_type": "composite",
                "result_fields": [],
                "unit": None,
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": "preserve_all",
            },
        }

        errors = validate_business_rules(
            plan,
            self.context,
            "请列出主要经营指标及排名，哪些指标表现较好，"
            "哪些表现较差？",
        )

        messages = "\n".join(
            error["message"] for error in errors
        )
        self.assertIn(
            "ZB001的绩效排名",
            messages,
        )
        self.assertIn(
            "ZB002的绩效排名",
            messages,
        )


if __name__ == "__main__":
    unittest.main()
