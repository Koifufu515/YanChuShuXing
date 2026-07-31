from __future__ import annotations

import copy
import unittest

from app.application.query_plan_normalization import (
    normalize_query_plan,
)


class DefaultPerformanceRankingNormalizationTest(
    unittest.TestCase
):
    @staticmethod
    def _plan(
        metric_id: str,
        order: str,
    ) -> dict:
        return {
            "status": {
                "code": "executable",
            },
            "metrics": {
                "requested_metric_ids": [
                    metric_id
                ],
                "source_metric_ids": [
                    metric_id
                ],
                "concept_ids": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": [
                        metric_id
                    ],
                    "output_ref": "raw",
                    "parameters": {},
                },
                {
                    "step": 2,
                    "operator_id": "OP011",
                    "input_refs": ["raw"],
                    "output_ref": "ranked",
                    "parameters": {
                        "order": order,
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "selected",
                    "parameters": {
                        "n": 3,
                        "direction": "bottom",
                    },
                },
            ],
            "checks": [],
            "output": {
                "answer_type": "ranking",
            },
        }

    def test_higher_is_better_default_ranking(
        self,
    ) -> None:
        plan = self._plan(
            "ZB011",
            "ascending",
        )

        normalized = normalize_query_plan(
            plan,
            (
                "2025年8月末，全省净利润"
                "排最后一名的是哪家？"
            ),
        )

        ranking = normalized[
            "operations"
        ][1]

        self.assertEqual(
            ranking["operator_id"],
            "OP012",
        )
        self.assertEqual(
            ranking["parameters"],
            {
                "metric_id": "ZB011",
                "performance_direction": (
                    "higher_is_better"
                ),
            },
        )

    def test_lower_is_better_default_ranking(
        self,
    ) -> None:
        plan = self._plan(
            "ZB013",
            "descending",
        )

        normalized = normalize_query_plan(
            plan,
            (
                "截至2025-04-30，"
                "不良贷款率排名最后的三家"
                "是哪些？"
            ),
        )

        ranking = normalized[
            "operations"
        ][1]

        self.assertEqual(
            ranking["operator_id"],
            "OP012",
        )
        self.assertEqual(
            ranking["parameters"],
            {
                "metric_id": "ZB013",
                "performance_direction": (
                    "lower_is_better"
                ),
            },
        )

    def test_explicit_numeric_order_keeps_op011(
        self,
    ) -> None:
        plan = self._plan(
            "ZB013",
            "descending",
        )
        original = copy.deepcopy(plan)

        normalized = normalize_query_plan(
            plan,
            (
                "按不良贷款率数值从高到低"
                "排名，列出最后三家。"
            ),
        )

        self.assertEqual(
            normalized["operations"],
            original["operations"],
        )

    def test_normalization_is_idempotent(
        self,
    ) -> None:
        plan = self._plan(
            "ZB012",
            "descending",
        )
        question = (
            "成本收入比排名最后的三家"
            "是哪些？"
        )

        once = normalize_query_plan(
            plan,
            question,
        )
        twice = normalize_query_plan(
            once,
            question,
        )

        self.assertEqual(
            twice,
            once,
        )


if __name__ == "__main__":
    unittest.main()
