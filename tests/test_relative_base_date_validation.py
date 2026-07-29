import copy
import json
import unittest
from pathlib import Path

from app.application.query_plan_validation import (
    validate_business_rules,
)
from tests.test_query_plan_backend import base_plan


def comparison_plan(base_date):
    plan = base_plan(
        operations=[
            {
                "step": 1,
                "operator_id": "OP021",
                "input_refs": [],
                "output_ref": "base_period",
                "parameters": {
                    "type": "previous_quarter_end",
                    "reference_date": "2025-11-30",
                },
            },
            {
                "step": 2,
                "operator_id": "OP001",
                "input_refs": ["ZB009"],
                "output_ref": "current_value",
                "parameters": {
                    "institution_id": "ORG012",
                    "date": "2025-11-30",
                },
            },
            {
                "step": 3,
                "operator_id": "OP001",
                "input_refs": ["ZB009"],
                "output_ref": "base_value",
                "parameters": {
                    "institution_id": "ORG012",
                    "date": base_date,
                },
            },
            {
                "step": 4,
                "operator_id": "OP003",
                "input_refs": [
                    "current_value",
                    "base_value",
                ],
                "output_ref": "change",
                "parameters": {
                    "direction": "A_minus_B",
                },
            },
        ],
        checks=[
            {
                "type": "record_exists",
                "parameters": {
                    "metric_ids": ["ZB009"],
                },
            },
            {
                "type": "unit_consistency",
                "parameters": {
                    "metric_ids": ["ZB009"],
                },
            },
        ],
    )
    plan["institutions"]["targets"] = [
        {
            "institution_id": "ORG012",
            "role": "target",
        }
    ]
    plan["metrics"] = {
        "requested_metric_ids": ["ZB009"],
        "source_metric_ids": ["ZB009"],
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
                "date": "2025-11-30",
                "start_date": None,
                "end_date": None,
            },
            {
                "type": "previous_quarter_end",
                "date": base_date,
                "start_date": None,
                "end_date": None,
            },
        ],
    }
    return plan


class RelativeBaseDateValidationTest(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.context = json.loads(
            (
                root
                / "config/query_planner/"
                "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )
        cls.question = (
            "江苏省L市农商行的营业收入在"
            "2025-11-30，与上季度末相比"
            "变动了多少？"
        )

    def test_correct_previous_quarter_end_passes(
        self,
    ):
        errors = validate_business_rules(
            comparison_plan("2025-09-30"),
            self.context,
            self.question,
        )
        self.assertEqual(errors, [])

    def test_three_month_offset_is_rejected(
        self,
    ):
        errors = validate_business_rules(
            comparison_plan("2025-08-31"),
            self.context,
            self.question,
        )
        messages = " ".join(
            item["message"] for item in errors
        )
        self.assertIn("2025-09-30", messages)
        self.assertIn("必须由OP001实际读取", messages)


if __name__ == "__main__":
    unittest.main()
