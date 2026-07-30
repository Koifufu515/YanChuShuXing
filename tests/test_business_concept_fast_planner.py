from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.adapters.planning.business_concept_fast_planner import (
    BusinessConceptFastPlanner,
    RoutingQueryPlanner,
)


class RecordingFallbackPlanner:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def plan(self, question: str):
        self.questions.append(question)
        raise RuntimeError("进入 DeepSeek 回退规划器")


class BusinessConceptFastPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        config_dir = root / "config" / "query_planner"

        cls.context = json.loads(
            (
                config_dir
                / "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )
        cls.schema = json.loads(
            (
                config_dir
                / "query_plan.schema.json"
            ).read_text(encoding="utf-8")
        )

    def build_router(
        self,
    ) -> tuple[RoutingQueryPlanner, RecordingFallbackPlanner]:
        fallback = RecordingFallbackPlanner()

        router = RoutingQueryPlanner(
            fast_planner=BusinessConceptFastPlanner(
                schema=self.schema,
                context=self.context,
            ),
            fallback_planner=fallback,
        )

        return router, fallback

    def test_main_metrics_question_uses_fast_path(self) -> None:
        router, fallback = self.build_router()

        question = (
            "请列出江苏省G市农商行在2025-11-30的"
            "主要经营指标及排名，哪些指标表现较好，"
            "哪些指标表现较差？"
        )

        result = router.plan(question)

        self.assertTrue(result.success)
        self.assertEqual(
            result.model,
            "deterministic-business-concept",
        )
        self.assertEqual(result.latency_ms, 0.0)
        self.assertFalse(result.repair_attempted)
        self.assertEqual(fallback.questions, [])

        plan = result.query_plan

        self.assertEqual(
            plan["institutions"]["targets"],
            [
                {
                    "institution_id": "ORG007",
                    "role": "target",
                }
            ],
        )
        self.assertEqual(
            plan["metrics"]["concept_ids"],
            ["BC001", "BC002", "BC003"],
        )

    def test_fast_plan_contains_complete_rankings(self) -> None:
        router, _ = self.build_router()

        question = (
            "请列出江苏省J市农商行在2025-11-30的"
            "主要经营指标及排名，哪些指标表现较好，"
            "哪些指标表现较差？"
        )

        result = router.plan(question)
        operations = result.query_plan["operations"]

        rank_operations = [
            operation
            for operation in operations
            if operation["operator_id"] in {
                "OP011",
                "OP012",
            }
        ]

        self.assertEqual(len(rank_operations), 9)
        self.assertEqual(
            operations[-1]["operator_id"],
            "OP019",
        )

        final_refs = operations[-1]["input_refs"]

        for operation in rank_operations:
            self.assertIn(
                operation["output_ref"],
                final_refs,
            )

    def test_fast_plan_contains_required_checks(self) -> None:
        router, _ = self.build_router()

        question = (
            "请列出江苏省A市农商行在2025-11-30的"
            "主要经营指标及排名，哪些指标表现较好，"
            "哪些指标表现较差？"
        )

        result = router.plan(question)

        check_types = {
            check["type"]
            for check in result.query_plan["checks"]
        }

        self.assertEqual(
            check_types,
            {
                "record_exists",
                "institution_completeness",
                "metric_completeness",
                "denominator_nonzero",
                "unrounded_comparison",
                "tie_preservation",
            },
        )

    def test_short_generic_metrics_question_uses_fast_path(
        self,
    ) -> None:
        router, fallback = self.build_router()

        question = (
            "江苏省F市农商行在2025-11-30的"
            "指标中哪些表现较好？哪些表现较差？"
        )

        result = router.plan(question)

        self.assertTrue(result.success)
        self.assertEqual(
            result.model,
            "deterministic-business-concept",
        )
        self.assertEqual(
            result.query_plan["time"]["mode"],
            "point",
        )
        self.assertEqual(
            result.query_plan["time"]["dates"],
            ["2025-11-30"],
        )
        self.assertEqual(fallback.questions, [])

    def test_chinese_date_paraphrase_uses_fast_path(
        self,
    ) -> None:
        router, fallback = self.build_router()

        question = (
            "请分析江苏省E市农商行在"
            "2026年2月28日的主要经营指标及"
            "全省排名，说明哪些指标表现较好，"
            "哪些指标表现较差。"
        )

        result = router.plan(question)

        self.assertTrue(result.success)
        self.assertEqual(
            result.model,
            "deterministic-business-concept",
        )
        self.assertEqual(
            result.query_plan["time"]["mode"],
            "point",
        )
        self.assertEqual(
            result.query_plan["time"]["dates"],
            ["2026-02-28"],
        )
        self.assertEqual(fallback.questions, [])

    def test_explicit_metric_subset_uses_fallback(
        self,
    ) -> None:
        router, fallback = self.build_router()

        question = (
            "江苏省F市农商行在2025-11-30的"
            "存款和贷款指标中哪些表现较好？"
            "哪些表现较差？"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "进入 DeepSeek 回退规划器",
        ):
            router.plan(question)

        self.assertEqual(
            fallback.questions,
            [question],
        )

    def test_other_question_uses_fallback(self) -> None:
        router, fallback = self.build_router()

        question = (
            "请分析江苏省G市农商行在2025-11-30的"
            "盈利能力和收入结构。"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "进入 DeepSeek 回退规划器",
        ):
            router.plan(question)

        self.assertEqual(
            fallback.questions,
            [question],
        )


if __name__ == "__main__":
    unittest.main()
