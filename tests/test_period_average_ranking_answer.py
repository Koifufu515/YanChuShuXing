from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    RankingOverviewFacts,
)
from app.application.query_plan_normalization import (
    normalize_query_plan,
)


class PeriodAverageRankingAnswerTest(
    unittest.TestCase
):
    def test_normalizes_malformed_bottom_plan(
        self,
    ) -> None:
        plan = {
            "status": {
                "code": "executable",
                "reason": None,
                "clarification_question": None,
            },
            "institutions": {
                "targets": [],
                "comparison_population": {
                    "type": (
                        "all_official_institutions"
                    ),
                    "institution_ids": [
                        f"ORG{index:03d}"
                        for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB032"
                ],
                "source_metric_ids": [
                    "ZB002"
                ],
                "concept_ids": [],
            },
            "time": {
                "mode": "range",
                "dates": [],
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "grain": "day",
                "comparison_periods": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB002"],
                    "output_ref": "loan_raw",
                    "parameters": {
                        "institution_ids": [
                            f"ORG{index:03d}"
                            for index
                            in range(1, 14)
                        ],
                        "start_date": (
                            "2025-01-01"
                        ),
                        "end_date": (
                            "2025-12-31"
                        ),
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP009",
                    "input_refs": ["loan_raw"],
                    "output_ref": "loan_avg",
                    "parameters": {
                        "group_by": [
                            "institution_id"
                        ],
                        "metric_id": "ZB002",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP012",
                    "input_refs": ["loan_avg"],
                    "output_ref": "loan_rank",
                    "parameters": {
                        "metric_id": "ZB002",
                        "performance_direction": (
                            "higher_is_better"
                        ),
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP013",
                    "input_refs": ["loan_rank"],
                    "output_ref": "bottom3",
                    "parameters": {
                        "n": 3,
                        "direction": "bottom",
                    },
                },
            ],
            "checks": [
                {
                    "type": "record_exists",
                    "parameters": {
                        "metric_ids": ["ZB002"]
                    },
                },
                {
                    "type": "date_completeness",
                    "parameters": {
                        "start_date": (
                            "2025-01-01"
                        ),
                        "end_date": (
                            "2025-12-31"
                        ),
                        "grain": "day",
                    },
                },
                {
                    "type": "tie_preservation",
                    "parameters": {
                        "metric_ids": ["ZB002"]
                    },
                },
            ],
            "output": {
                "answer_type": "ranking",
                "result_fields": [
                    "institution_id",
                    "average_loan_balance",
                    "rank",
                ],
                "unit": "亿元",
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": (
                    "preserve_all"
                ),
            },
        }

        normalized = normalize_query_plan(
            plan,
            (
                "2025年全年13家农商行的"
                "日均贷款余额排名后三的是"
                "哪些机构？"
            ),
        )

        self.assertEqual(
            normalized["metrics"][
                "requested_metric_ids"
            ],
            ["ZB032"],
        )
        self.assertEqual(
            normalized["metrics"][
                "source_metric_ids"
            ],
            ["ZB002"],
        )
        self.assertEqual(
            normalized["operations"][1][
                "parameters"
            ],
            {},
        )
        self.assertEqual(
            normalized["operations"][2][
                "parameters"
            ],
            {
                "metric_id": "ZB032",
                "performance_direction": (
                    "higher_is_better"
                ),
            },
        )
        self.assertEqual(
            normalized["output"][
                "result_fields"
            ],
            [
                "institution_id",
                "metric_value",
                "rank",
            ],
        )

    def test_extracts_and_composes_range_ranking(
        self,
    ) -> None:
        ranked = []

        for rank in range(1, 14):
            ranked.append(
                {
                    "institution_id": (
                        f"ORG{rank:03d}"
                    ),
                    "institution_name": (
                        f"江苏省{rank}市农商行"
                    ),
                    "date": None,
                    "start_date": (
                        "2025-01-01"
                    ),
                    "end_date": (
                        "2025-12-31"
                    ),
                    "metric_id": "ZB001",
                    "metric_name": (
                        "各项存款余额"
                    ),
                    "unit": "亿元",
                    "value": (
                        Decimal(200 - rank)
                    ),
                    "rank": rank,
                }
            )

        plan = {
            "institutions": {
                "targets": [],
                "comparison_population": {
                    "type": (
                        "all_official_institutions"
                    ),
                    "institution_ids": [
                        f"ORG{index:03d}"
                        for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB031"
                ],
                "source_metric_ids": [
                    "ZB001"
                ],
                "concept_ids": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP012",
                    "input_refs": ["average_raw"],
                    "output_ref": "average_rank",
                    "parameters": {
                        "metric_id": "ZB031",
                        "performance_direction": (
                            "higher_is_better"
                        ),
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP013",
                    "input_refs": [
                        "average_rank"
                    ],
                    "output_ref": "top3",
                    "parameters": {
                        "n": 3,
                        "direction": "top",
                    },
                },
            ],
        }

        context = {
            "average_rank": ExecutionValue(
                kind="records",
                data=ranked,
                unit="亿元",
            ),
            "top3": ExecutionValue(
                kind="records",
                data=ranked[:3],
                unit="亿元",
            ),
        }

        facts = (
            DeterministicQueryPlanExecutor
            ._ranking_overview_facts(
                plan,
                context,
            )
        )

        self.assertIsInstance(
            facts,
            RankingOverviewFacts,
        )
        assert facts is not None

        self.assertEqual(
            facts.selection_mode,
            "top_n",
        )
        self.assertEqual(
            facts.requested_n,
            3,
        )
        self.assertEqual(
            facts.period_start,
            "2025-01-01",
        )
        self.assertEqual(
            facts.period_end,
            "2025-12-31",
        )
        self.assertEqual(
            facts.rankings[0]
            .metric.metric_id,
            "ZB031",
        )
        self.assertEqual(
            facts.rankings[0]
            .metric.metric_name,
            "日均存款余额",
        )

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "全年日均存款余额"
                    "排名前三。"
                ),
                query_plan={},
                facts=facts,
            )
        )

        self.assertIn(
            "日均存款余额全省排名前3",
            answer.headline,
        )
        self.assertIn(
            (
                "在 2025 年 1 月 1 日"
                "至2025 年 12 月 31 日期间"
            ),
            answer.summary,
        )
        self.assertNotIn(
            "截至 2025 年 12 月 31 日",
            answer.summary,
        )


    def test_default_ranking_converts_op011_to_op012(
        self,
    ) -> None:
        plan = {
            "status": {
                "code": "executable",
            },
            "institutions": {
                "targets": [],
                "comparison_population": {
                    "type": (
                        "all_official_institutions"
                    ),
                    "institution_ids": [
                        f"ORG{index:03d}"
                        for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB031"
                ],
                "source_metric_ids": [
                    "ZB001"
                ],
                "concept_ids": [],
            },
            "time": {
                "mode": "range",
                "dates": [],
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "grain": "day",
                "comparison_periods": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "raw",
                    "parameters": {
                        "start_date": (
                            "2025-01-01"
                        ),
                        "end_date": (
                            "2025-12-31"
                        ),
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP009",
                    "input_refs": ["raw"],
                    "output_ref": "average",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP011",
                    "input_refs": ["average"],
                    "output_ref": "ranked",
                    "parameters": {
                        "order": "descending"
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "top3",
                    "parameters": {
                        "n": 3,
                        "direction": "top",
                    },
                },
            ],
            "checks": [],
            "output": {
                "answer_type": "ranking",
                "result_fields": [
                    "institution_id",
                    "metric_value",
                    "rank",
                ],
                "unit": "亿元",
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": (
                    "preserve_all"
                ),
            },
        }

        normalized = normalize_query_plan(
            plan,
            (
                "2025年全年13家农商行的"
                "日均存款余额排名前三的是"
                "哪些机构？"
            ),
        )

        ranking = normalized[
            "operations"
        ][2]

        self.assertEqual(
            ranking["operator_id"],
            "OP012",
        )
        self.assertEqual(
            ranking["parameters"],
            {
                "metric_id": "ZB031",
                "performance_direction": (
                    "higher_is_better"
                ),
            },
        )

    def test_explicit_numeric_ranking_preserves_op011(
        self,
    ) -> None:
        plan = {
            "status": {
                "code": "executable",
            },
            "institutions": {
                "targets": [],
                "comparison_population": {
                    "type": (
                        "all_official_institutions"
                    ),
                    "institution_ids": [
                        f"ORG{index:03d}"
                        for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB031"
                ],
                "source_metric_ids": [
                    "ZB001"
                ],
                "concept_ids": [],
            },
            "time": {
                "mode": "range",
                "dates": [],
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "grain": "day",
                "comparison_periods": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "raw",
                    "parameters": {
                        "start_date": (
                            "2025-01-01"
                        ),
                        "end_date": (
                            "2025-12-31"
                        ),
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP009",
                    "input_refs": ["raw"],
                    "output_ref": "average",
                    "parameters": {},
                },
                {
                    "step": 3,
                    "operator_id": "OP011",
                    "input_refs": ["average"],
                    "output_ref": "ranked",
                    "parameters": {
                        "order": "ascending"
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP013",
                    "input_refs": ["ranked"],
                    "output_ref": "top3",
                    "parameters": {
                        "n": 3,
                        "direction": "top",
                    },
                },
            ],
            "checks": [],
            "output": {
                "answer_type": "ranking",
                "result_fields": [
                    "institution_id",
                    "metric_value",
                    "rank",
                ],
                "unit": "亿元",
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                },
                "tie_policy": (
                    "preserve_all"
                ),
            },
        }

        normalized = normalize_query_plan(
            plan,
            (
                "按日均存款余额数值从低到高"
                "列出前3家农商行。"
            ),
        )

        ranking = normalized[
            "operations"
        ][2]

        self.assertEqual(
            ranking["operator_id"],
            "OP011",
        )
        self.assertEqual(
            ranking["parameters"],
            {
                "order": "ascending",
            },
        )

if __name__ == "__main__":
    unittest.main()
