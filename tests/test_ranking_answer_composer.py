from __future__ import annotations

import unittest

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.application.answer_models import (
    InstitutionRef,
    MetricRankingFacts,
    MetricRef,
    RankingItem,
    RankingOverviewFacts,
)


class RankingAnswerComposerTest(
    unittest.TestCase
):
    def test_multi_metric_target_ranks_use_table_without_chart(
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

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "江苏省M市农商行三方面"
                    "排名各是多少？"
                ),
                query_plan={},
                facts=facts,
            )
        )

        self.assertEqual(
            answer.answer_type,
            "ranking",
        )
        self.assertIn(
            "多指标全省排名",
            answer.headline,
        )
        self.assertIn(
            "各项贷款余额绩效排名第7名（按数值从高到低）",
            answer.summary,
        )
        self.assertIn(
            "不良贷款率绩效排名第8名（按数值从低到高）",
            answer.summary,
        )
        self.assertIn(
            "净利润绩效排名第6名（按数值从高到低）",
            answer.summary,
        )
        self.assertEqual(
            answer.key_metrics,
            [],
        )
        self.assertIsNone(
            answer.chart_spec
        )

        self.assertIsNotNone(
            answer.table
        )
        assert answer.table is not None

        self.assertEqual(
            answer.table.columns,
            [
                "机构",
                "指标",
                "指标值",
                "单位",
                "全省排名",
                "排名口径",
            ],
        )
        self.assertEqual(
            len(answer.table.rows),
            3,
        )
        self.assertEqual(
            [
                row[4]
                for row in answer.table.rows
            ],
            [
                "第7名",
                "第8名",
                "第6名",
            ],
        )
        self.assertEqual(
            [
                row[5]
                for row in answer.table.rows
            ],
            [
                "绩效排名（高值优先）",
                "绩效排名（低值优先）",
                "绩效排名（高值优先）",
            ],
        )

    def test_lower_is_better_target_rank_is_explicit(
        self,
    ) -> None:
        facts = RankingOverviewFacts(
            period="2025-12-31",
            selection_mode="target",
            rankings=[
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
                            institution=InstitutionRef(
                                institution_id="ORG002",
                                institution_name=(
                                    "江苏省B市农商行"
                                ),
                            ),
                            value=0.91,
                            rank=2,
                        )
                    ],
                )
            ],
        )

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "江苏省B市农商行的不良贷款率"
                    "全省排名是多少？"
                ),
                query_plan={},
                facts=facts,
            )
        )

        expected = (
            "江苏省B市农商行不良贷款率"
            "绩效排名第2名（按数值从低到高）"
        )

        self.assertEqual(
            answer.headline,
            expected,
        )
        self.assertIn(
            "江苏省B市农商行在全省13家农商行中",
            answer.summary,
        )
        self.assertIn(
            "不良贷款率绩效排名第2名",
            answer.summary,
        )
        self.assertIn(
            "按数值从低到高",
            answer.summary,
        )

        self.assertIsNotNone(answer.table)
        assert answer.table is not None

        self.assertEqual(
            answer.table.rows[0][3],
            "第2名",
        )
        self.assertEqual(
            answer.table.rows[0][4],
            "绩效排名（低值优先）",
        )

    def test_top_n_boundary_tie_uses_value_bar_chart(
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
                                "ORG001",
                                "江苏省A市农商行",
                            ),
                            value=80,
                            rank=1,
                        ),
                        RankingItem(
                            institution=InstitutionRef(
                                "ORG002",
                                "江苏省B市农商行",
                            ),
                            value=70,
                            rank=2,
                        ),
                        RankingItem(
                            institution=InstitutionRef(
                                "ORG003",
                                "江苏省C市农商行",
                            ),
                            value=65,
                            rank=3,
                        ),
                        RankingItem(
                            institution=InstitutionRef(
                                "ORG004",
                                "江苏省D市农商行",
                            ),
                            value=65,
                            rank=3,
                        ),
                    ],
                )
            ],
        )

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "各项存款余额排名前三。"
                ),
                query_plan={},
                facts=facts,
            )
        )

        self.assertIn(
            "第3名存在并列",
            answer.summary,
        )

        self.assertIsNotNone(
            answer.chart_spec
        )
        assert answer.chart_spec is not None

        self.assertEqual(
            answer.chart_spec.chart_type,
            "bar",
        )
        self.assertEqual(
            answer.chart_spec.series[0].values,
            [80, 70, 65, 65],
        )
        self.assertEqual(
            answer.chart_spec.unit,
            "亿元",
        )

        self.assertIsNotNone(
            answer.table
        )
        assert answer.table is not None

        self.assertEqual(
            [
                row[3]
                for row in answer.table.rows
            ],
            [
                "第1名",
                "第2名",
                "第3名",
                "第3名",
            ],
        )


if __name__ == "__main__":
    unittest.main()
