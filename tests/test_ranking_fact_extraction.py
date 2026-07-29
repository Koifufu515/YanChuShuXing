from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    RankingOverviewFacts,
)


def ranked_records(
    metric_id: str,
    metric_name: str,
    unit: str,
    target_rank: int,
    lower_is_better: bool = False,
) -> list[dict[str, object]]:
    other_ids = [
        f"ORG{index:03d}"
        for index in range(1, 13)
    ]
    records: list[dict[str, object]] = []

    for rank in range(1, 14):
        if rank == target_rank:
            institution_id = "ORG013"
            institution_name = (
                "江苏省M市农商行"
            )
        else:
            institution_id = other_ids.pop(0)
            institution_name = (
                f"江苏省{institution_id}农商行"
            )

        value = (
            Decimal(rank)
            if lower_is_better
            else Decimal(100 - rank)
        )

        records.append(
            {
                "institution_id": institution_id,
                "institution_name": (
                    institution_name
                ),
                "date": "2025-12-31",
                "metric_id": metric_id,
                "metric_name": metric_name,
                "unit": unit,
                "value": value,
                "rank": rank,
            }
        )

    return records


class RankingFactExtractionTest(
    unittest.TestCase
):
    def test_extracts_multi_metric_target_ranks(
        self,
    ) -> None:
        loan = ranked_records(
            "ZB002",
            "各项贷款余额",
            "亿元",
            target_rank=7,
        )
        npl = ranked_records(
            "ZB013",
            "不良贷款率",
            "%",
            target_rank=8,
            lower_is_better=True,
        )
        profit = ranked_records(
            "ZB011",
            "净利润",
            "万元",
            target_rank=6,
        )

        plan = {
            "institutions": {
                "targets": [
                    {
                        "institution_id": "ORG013",
                        "institution_name": (
                            "江苏省M市农商行"
                        ),
                    }
                ],
                "comparison_population": {
                    "type": "province_all",
                    "institution_ids": [],
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
                "concept_ids": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP012",
                    "input_refs": ["loan_raw"],
                    "output_ref": "loan_rank",
                    "parameters": {
                        "performance_direction": (
                            "higher_is_better"
                        ),
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP013",
                    "input_refs": ["loan_rank"],
                    "output_ref": "loan_all",
                    "parameters": {
                        "n": 13,
                        "direction": "top",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP012",
                    "input_refs": ["npl_raw"],
                    "output_ref": "npl_rank",
                    "parameters": {
                        "performance_direction": (
                            "lower_is_better"
                        ),
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP013",
                    "input_refs": ["npl_rank"],
                    "output_ref": "npl_all",
                    "parameters": {
                        "n": 13,
                        "direction": "top",
                    },
                },
                {
                    "step": 5,
                    "operator_id": "OP012",
                    "input_refs": ["profit_raw"],
                    "output_ref": "profit_rank",
                    "parameters": {
                        "performance_direction": (
                            "higher_is_better"
                        ),
                    },
                },
                {
                    "step": 6,
                    "operator_id": "OP013",
                    "input_refs": ["profit_rank"],
                    "output_ref": "profit_all",
                    "parameters": {
                        "n": 13,
                        "direction": "top",
                    },
                },
                {
                    "step": 7,
                    "operator_id": "OP019",
                    "input_refs": [
                        "loan_all",
                        "npl_all",
                        "profit_all",
                    ],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
        }

        context = {
            "loan_rank": ExecutionValue(
                kind="records",
                data=loan,
                unit="亿元",
            ),
            "loan_all": ExecutionValue(
                kind="records",
                data=loan,
                unit="亿元",
            ),
            "npl_rank": ExecutionValue(
                kind="records",
                data=npl,
                unit="%",
            ),
            "npl_all": ExecutionValue(
                kind="records",
                data=npl,
                unit="%",
            ),
            "profit_rank": ExecutionValue(
                kind="records",
                data=profit,
                unit="万元",
            ),
            "profit_all": ExecutionValue(
                kind="records",
                data=profit,
                unit="万元",
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
            "target",
        )
        self.assertIsNone(
            facts.requested_n
        )
        self.assertEqual(
            facts.period,
            "2025-12-31",
        )
        self.assertEqual(
            [
                ranking.metric.metric_id
                for ranking in facts.rankings
            ],
            [
                "ZB002",
                "ZB013",
                "ZB011",
            ],
        )
        self.assertEqual(
            [
                ranking.items[0].rank
                for ranking in facts.rankings
            ],
            [7, 8, 6],
        )
        self.assertEqual(
            [
                ranking.population_size
                for ranking in facts.rankings
            ],
            [13, 13, 13],
        )

    def test_extracts_top_n_with_boundary_tie(
        self,
    ) -> None:
        ranked = [
            {
                "institution_id": "ORG001",
                "institution_name": "江苏省A市农商行",
                "date": "2025-12-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("80"),
                "rank": 1,
            },
            {
                "institution_id": "ORG002",
                "institution_name": "江苏省B市农商行",
                "date": "2025-12-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("70"),
                "rank": 2,
            },
            {
                "institution_id": "ORG003",
                "institution_name": "江苏省C市农商行",
                "date": "2025-12-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("65"),
                "rank": 3,
            },
            {
                "institution_id": "ORG004",
                "institution_name": "江苏省D市农商行",
                "date": "2025-12-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("65"),
                "rank": 3,
            },
            {
                "institution_id": "ORG005",
                "institution_name": "江苏省E市农商行",
                "date": "2025-12-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("60"),
                "rank": 5,
            },
        ]

        plan = {
            "institutions": {
                "targets": [],
                "comparison_population": {
                    "type": "province_all",
                    "institution_ids": [],
                },
            },
            "metrics": {
                "requested_metric_ids": ["ZB001"],
                "source_metric_ids": ["ZB001"],
                "concept_ids": [],
            },
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP012",
                    "input_refs": ["deposit_raw"],
                    "output_ref": "deposit_rank",
                    "parameters": {
                        "performance_direction": (
                            "higher_is_better"
                        ),
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP013",
                    "input_refs": ["deposit_rank"],
                    "output_ref": "deposit_top3",
                    "parameters": {
                        "n": 3,
                        "direction": "top",
                    },
                },
            ],
        }

        context = {
            "deposit_rank": ExecutionValue(
                kind="records",
                data=ranked,
                unit="亿元",
            ),
            "deposit_top3": ExecutionValue(
                kind="records",
                data=ranked[:4],
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
            facts.rankings[0].population_size,
            5,
        )
        self.assertEqual(
            [
                item.rank
                for item
                in facts.rankings[0].items
            ],
            [1, 2, 3, 3],
        )


if __name__ == "__main__":
    unittest.main()
