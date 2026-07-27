import json
import unittest
from pathlib import Path

from app.application.query_plan_validation import validate_business_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = (
    PROJECT_ROOT
    / "config"
    / "query_planner"
    / "query_planner_context.json"
)
PROMPT_PATH = (
    PROJECT_ROOT
    / "config"
    / "query_planner"
    / "query_planner_prompt.md"
)


class BusinessConceptDefinitionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = json.loads(
            CONTEXT_PATH.read_text(encoding="utf-8")
        )
        cls.concepts = {
            item["concept_id"]: item
            for item in cls.context["business_concepts"]
        }

    def test_all_business_concepts_are_frozen(self):
        self.assertEqual(
            set(self.concepts),
            {f"BC{index:03d}" for index in range(1, 8)},
        )
        self.assertEqual(
            {
                item.get("status")
                for item in self.concepts.values()
            },
            {"已有项目口径"},
        )

    def test_main_operating_metrics_are_exact(self):
        concept = self.concepts["BC001"]
        self.assertEqual(
            concept["related_metric_ids"],
            [
                "ZB001",
                "ZB002",
                "ZB022",
                "ZB013",
                "ZB015",
                "ZB016",
                "ZB017",
                "ZB011",
                "ZB012",
            ],
        )
        self.assertEqual(
            concept["classification_metric_ids"],
            [
                "ZB001",
                "ZB002",
                "ZB013",
                "ZB015",
                "ZB016",
                "ZB017",
                "ZB011",
                "ZB012",
            ],
        )

    def test_dimension_concepts_are_exact(self):
        self.assertEqual(
            self.concepts["BC004"]["related_metric_ids"],
            ["ZB001", "ZB002", "ZB022"],
        )
        self.assertEqual(
            self.concepts["BC005"]["related_metric_ids"],
            ["ZB013"],
        )
        self.assertEqual(
            self.concepts["BC006"]["related_metric_ids"],
            ["ZB011"],
        )
        self.assertEqual(
            self.concepts["BC007"]["related_metric_ids"],
            ["ZB008", "ZB007", "ZB009", "ZB034"],
        )

    def test_pending_status_is_rejected_when_no_concept_is_pending(self):
        plan = {
            "status": {
                "code": "pending_project_definition",
                "reason": "主要经营指标待确认。",
                "clarification_question": None,
            },
            "institutions": {
                "targets": [
                    {
                        "institution_id": "ORG007",
                        "role": "target",
                    }
                ],
                "comparison_population": {
                    "type": "all_official_institutions",
                    "institution_ids": [
                        f"ORG{index:03d}"
                        for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": [],
                "source_metric_ids": [],
                "concept_ids": ["BC001", "BC002", "BC003"],
            },
            "time": {
                "mode": "point",
                "dates": ["2025-11-30"],
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
            "请列出江苏省G市农商行在2025-11-30的"
            "主要经营指标及排名，哪些指标表现较好，"
            "哪些表现较差？",
        )

        self.assertTrue(
            any(
                "不得使用pending_project_definition"
                in error["message"]
                for error in errors
            ),
            errors,
        )

    def test_prompt_contains_frozen_expansion_rules(self):
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "BC001主要经营指标固定展开为"
            "ZB001、ZB002、ZB022",
            prompt,
        )
        self.assertIn(
            "ZB022存贷比只做OP011纯数值降序排名",
            prompt,
        )
        self.assertIn(
            "BC007收入结构固定返回ZB008净利息收入",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
