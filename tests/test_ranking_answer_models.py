from __future__ import annotations

import unittest

from app.application.answer_models import (
    InstitutionRef,
    MetricRankingFacts,
    MetricRef,
    RankingItem,
    RankingOverviewFacts,
)


class RankingAnswerModelsTest(unittest.TestCase):
    def test_preserves_top_n_boundary_ties(
        self,
    ) -> None:
        facts = RankingOverviewFacts(
            period="2025-12-31",
            selection_mode="top_n",
            requested_n=3,
            rankings=[
                MetricRankingFacts(
                    metric=MetricRef(
                        metric_id="ZB001",
                        metric_name="各项存款余额",
                        unit="亿元",
                        performance_direction=(
                            "higher_is_better"
                        ),
                    ),
                    population_size=13,
                    ranking_method="performance",
                    items=[
                        RankingItem(
                            institution=InstitutionRef(
                                institution_id="ORG001",
                                institution_name=(
                                    "江苏省A市农商行"
                                ),
                            ),
                            value=72.15,
                            rank=1,
                        ),
                        RankingItem(
                            institution=InstitutionRef(
                                institution_id="ORG002",
                                institution_name=(
                                    "江苏省B市农商行"
                                ),
                            ),
                            value=68.20,
                            rank=2,
                        ),
                        RankingItem(
                            institution=InstitutionRef(
                                institution_id="ORG003",
                                institution_name=(
                                    "江苏省C市农商行"
                                ),
                            ),
                            value=65.30,
                            rank=3,
                        ),
                        RankingItem(
                            institution=InstitutionRef(
                                institution_id="ORG004",
                                institution_name=(
                                    "江苏省D市农商行"
                                ),
                            ),
                            value=65.30,
                            rank=3,
                        ),
                    ],
                )
            ],
        )

        self.assertEqual(
            facts.answer_type,
            "ranking",
        )
        self.assertEqual(
            facts.selection_mode,
            "top_n",
        )
        self.assertEqual(
            facts.requested_n,
            3,
        )
        self.assertEqual(
            len(facts.rankings[0].items),
            4,
        )
        self.assertEqual(
            [
                item.rank
                for item in facts.rankings[0].items
            ],
            [1, 2, 3, 3],
        )

    def test_supports_multi_metric_target_ranks(
        self,
    ) -> None:
        institution = InstitutionRef(
            institution_id="ORG013",
            institution_name="江苏省M市农商行",
        )

        facts = RankingOverviewFacts(
            period="2025-12-31",
            selection_mode="target",
            rankings=[
                MetricRankingFacts(
                    metric=MetricRef(
                        metric_id="ZB002",
                        metric_name="各项贷款余额",
                        unit="亿元",
                        performance_direction=(
                            "higher_is_better"
                        ),
                    ),
                    population_size=13,
                    ranking_method="performance",
                    items=[
                        RankingItem(
                            institution=institution,
                            value=59.94,
                            rank=7,
                        )
                    ],
                ),
                MetricRankingFacts(
                    metric=MetricRef(
                        metric_id="ZB013",
                        metric_name="不良贷款率",
                        unit="%",
                        performance_direction=(
                            "lower_is_better"
                        ),
                    ),
                    population_size=13,
                    ranking_method="performance",
                    items=[
                        RankingItem(
                            institution=institution,
                            value=1.21,
                            rank=8,
                        )
                    ],
                ),
                MetricRankingFacts(
                    metric=MetricRef(
                        metric_id="ZB011",
                        metric_name="净利润",
                        unit="万元",
                        performance_direction=(
                            "higher_is_better"
                        ),
                    ),
                    population_size=13,
                    ranking_method="performance",
                    items=[
                        RankingItem(
                            institution=institution,
                            value=183.02,
                            rank=6,
                        )
                    ],
                ),
            ],
        )

        self.assertEqual(
            len(facts.rankings),
            3,
        )
        self.assertEqual(
            [
                ranking.items[0].rank
                for ranking in facts.rankings
            ],
            [7, 8, 6],
        )
        self.assertEqual(
            {
                ranking.metric.unit
                for ranking in facts.rankings
            },
            {"亿元", "%", "万元"},
        )


if __name__ == "__main__":
    unittest.main()
