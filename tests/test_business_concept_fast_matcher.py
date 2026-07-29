from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.application.business_concept_fast_matcher import (
    MainMetricsQueryMatch,
    match_main_metrics_query,
)


class BusinessConceptFastMatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        context_path = (
            root
            / "config"
            / "query_planner"
            / "query_planner_context.json"
        )
        cls.context = json.loads(
            context_path.read_text(encoding="utf-8")
        )

    def test_matches_standard_main_metrics_question(self) -> None:
        question = (
            "请列出江苏省G市农商行在2025-11-30的"
            "主要经营指标及排名，哪些指标表现较好，"
            "哪些指标表现较差？"
        )

        result = match_main_metrics_query(
            question,
            self.context,
        )

        self.assertEqual(
            result,
            MainMetricsQueryMatch(
                institution_id="ORG007",
                institution_name="江苏省G市农商行",
                data_date="2025-11-30",
            ),
        )

    def test_matches_question_with_spaces_and_shorter_wording(
        self,
    ) -> None:
        question = (
            "请列出江苏省 J 市农商行在 2025-11-30 的"
            "主要经营指标和排名，哪些指标较好，"
            "哪些指标较差？"
        )

        result = match_main_metrics_query(
            question,
            self.context,
        )

        self.assertEqual(
            result,
            MainMetricsQueryMatch(
                institution_id="ORG010",
                institution_name="江苏省J市农商行",
                data_date="2025-11-30",
            ),
        )

    def test_does_not_match_other_business_concepts(self) -> None:
        question = (
            "请分析江苏省G市农商行在2025-11-30的"
            "盈利能力和收入结构。"
        )

        self.assertIsNone(
            match_main_metrics_query(
                question,
                self.context,
            )
        )

    def test_does_not_match_when_date_is_missing(self) -> None:
        question = (
            "请列出江苏省G市农商行的主要经营指标及排名，"
            "哪些指标表现较好，哪些指标表现较差？"
        )

        self.assertIsNone(
            match_main_metrics_query(
                question,
                self.context,
            )
        )

    def test_does_not_match_out_of_range_date(self) -> None:
        question = (
            "请列出江苏省G市农商行在2026-05-31的"
            "主要经营指标及排名，哪些指标表现较好，"
            "哪些指标表现较差？"
        )

        self.assertIsNone(
            match_main_metrics_query(
                question,
                self.context,
            )
        )

    def test_does_not_match_multiple_institutions(self) -> None:
        question = (
            "请比较江苏省G市农商行和江苏省J市农商行"
            "在2025-11-30的主要经营指标及排名，"
            "哪些指标表现较好，哪些指标表现较差？"
        )

        self.assertIsNone(
            match_main_metrics_query(
                question,
                self.context,
            )
        )

    def test_does_not_match_partial_request(self) -> None:
        question = (
            "请列出江苏省G市农商行在2025-11-30的"
            "主要经营指标及排名。"
        )

        self.assertIsNone(
            match_main_metrics_query(
                question,
                self.context,
            )
        )


if __name__ == "__main__":
    unittest.main()
