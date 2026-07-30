from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.application.query_plan_validation import (
    validate_business_rules,
)


INSTITUTION_IDS = [
    f"ORG{index:03d}"
    for index in range(1, 14)
]


def operation(
    step: int,
    operator_id: str,
    input_refs: list[str],
    output_ref: str,
    parameters: dict,
) -> dict:
    return {
        "step": step,
        "operator_id": operator_id,
        "input_refs": input_refs,
        "output_ref": output_ref,
        "parameters": parameters,
    }


class ExplicitMetricConceptPriorityTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.context = json.loads(
            (
                root
                / "config/query_planner/"
                "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )

    def test_parenthetical_metrics_override_concept_defaults(
        self,
    ) -> None:
        question = (
            "2025年底，江苏省M市农商行在"
            "规模（贷款）、质量（不良率）、"
            "效益（净利润）三方面排名各是多少？"
        )

        plan = {
            "status": {
                "code": "executable",
                "reason": None,
                "clarification_question": None,
            },
            "institutions": {
                "targets": [
                    {
                        "institution_id": "ORG013",
                        "role": "target",
                    }
                ],
                "comparison_population": {
                    "type": (
                        "all_official_institutions"
                    ),
                    "institution_ids": (
                        INSTITUTION_IDS
                    ),
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB002",
                    "ZB013",
                    "ZB011",
                ],
                "source_metric_ids": [
                    "ZB002",
                    "ZB013",
                    "ZB011",
                ],
                "concept_ids": [
                    "BC004",
                    "BC005",
                    "BC006",
                ],
            },
            "time": {
                "mode": "point",
                "dates": ["2025-12-31"],
                "start_date": None,
                "end_date": None,
                "grain": "day",
                "comparison_periods": [],
            },
            "operations": [
                operation(
                    1,
                    "OP001",
                    ["ZB002"],
                    "loan_balance_all",
                    {
                        "institution_ids": (
                            INSTITUTION_IDS
                        ),
                        "date": "2025-12-31",
                    },
                ),
                operation(
                    2,
                    "OP001",
                    ["ZB013"],
                    "npl_ratio_all",
                    {
                        "institution_ids": (
                            INSTITUTION_IDS
                        ),
                        "date": "2025-12-31",
                    },
                ),
                operation(
                    3,
                    "OP001",
                    ["ZB011"],
                    "net_profit_all",
                    {
                        "institution_ids": (
                            INSTITUTION_IDS
                        ),
                        "date": "2025-12-31",
                    },
                ),
                operation(
                    4,
                    "OP011",
                    ["loan_balance_all"],
                    "loan_rank",
                    {"order": "descending"},
                ),
                operation(
                    5,
                    "OP012",
                    ["npl_ratio_all"],
                    "npl_perf_rank",
                    {
                        "metric_id": "ZB013",
                        "performance_direction": (
                            "lower_is_better"
                        ),
                    },
                ),
                operation(
                    6,
                    "OP012",
                    ["net_profit_all"],
                    "profit_perf_rank",
                    {
                        "metric_id": "ZB011",
                        "performance_direction": (
                            "higher_is_better"
                        ),
                    },
                ),
                operation(
                    7,
                    "OP013",
                    ["loan_rank"],
                    "loan_rank_all",
                    {
                        "n": 13,
                        "direction": "top",
                    },
                ),
                operation(
                    8,
                    "OP013",
                    ["npl_perf_rank"],
                    "npl_rank_all",
                    {
                        "n": 13,
                        "direction": "top",
                    },
                ),
                operation(
                    9,
                    "OP013",
                    ["profit_perf_rank"],
                    "profit_rank_all",
                    {
                        "n": 13,
                        "direction": "top",
                    },
                ),
                operation(
                    10,
                    "OP019",
                    [
                        "loan_rank_all",
                        "npl_rank_all",
                        "profit_rank_all",
                    ],
                    "final_result",
                    {},
                ),
            ],
            "checks": [
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": [
                            "ZB002",
                            "ZB013",
                            "ZB011",
                        ],
                    },
                },
                {
                    "type": (
                        "institution_completeness"
                    ),
                    "parameters": {},
                },
                {
                    "type": "metric_completeness",
                    "parameters": {
                        "metric_ids": [
                            "ZB002",
                            "ZB013",
                            "ZB011",
                        ],
                    },
                },
                {
                    "type": "unrounded_comparison",
                    "parameters": {
                        "metric_ids": [
                            "ZB002",
                            "ZB013",
                            "ZB011",
                        ],
                    },
                },
                {
                    "type": "tie_preservation",
                    "parameters": {
                        "metric_ids": [
                            "ZB002",
                            "ZB013",
                            "ZB011",
                        ],
                    },
                },
            ],
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
            question,
        )

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
