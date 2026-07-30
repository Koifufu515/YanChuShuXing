from __future__ import annotations

import unittest

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.application.answer_models import (
    InstitutionRef,
    MainMetricFact,
    MainMetricsOverviewFacts,
)


class MainMetricsAnswerComposerTest(unittest.TestCase):
    def test_composes_table_without_mixed_unit_chart(
        self,
    ) -> None:
        facts = MainMetricsOverviewFacts(
            subject=InstitutionRef(
                institution_id="ORG007",
                institution_name="江苏省G市农商行",
            ),
            period="2025-11-30",
            metrics=[
                MainMetricFact(
                    metric_id="ZB001",
                    metric_name="各项存款余额",
                    value=120.5,
                    unit="亿元",
                    rank=2,
                    performance_direction=(
                        "higher_is_better"
                    ),
                    performance_band="better",
                ),
                MainMetricFact(
                    metric_id="ZB013",
                    metric_name="成本收入比",
                    value=31.2,
                    unit="%",
                    rank=11,
                    performance_direction=(
                        "lower_is_better"
                    ),
                    performance_band="worse",
                ),
                MainMetricFact(
                    metric_id="ZB022",
                    metric_name="存贷比",
                    value=76.25,
                    unit="%",
                    rank=5,
                    performance_direction=None,
                    performance_band="numeric_only",
                ),
            ],
        )

        answer = DeterministicAnswerComposer().compose(
            question="主要经营指标分析",
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.answer_type,
            "main_metrics_overview",
        )
        self.assertIsNone(answer.chart_spec)
        self.assertIsNotNone(answer.table)
        assert answer.table is not None

        self.assertEqual(
            answer.table.columns,
            [
                "指标",
                "数值",
                "单位",
                "全省排名",
                "表现判断",
            ],
        )
        self.assertEqual(
            len(answer.table.rows),
            3,
        )
        self.assertEqual(
            answer.table.rows[0][3],
            "第2名",
        )
        self.assertIn(
            "表现较好",
            answer.table.rows[0][4],
        )
        self.assertIn(
            "表现较差",
            answer.table.rows[1][4],
        )
        self.assertEqual(
            answer.table.rows[2][4],
            "仅数值排名",
        )
        self.assertIn(
            "存贷比仅按数值降序排名",
            answer.summary,
        )


if __name__ == "__main__":
    unittest.main()
