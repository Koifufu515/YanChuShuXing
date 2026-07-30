from __future__ import annotations

import unittest

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.application.answer_models import (
    InstitutionRef,
    MetricRef,
    TrendOverviewFacts,
    TrendPoint,
    TrendSeries,
)


class TrendAnswerComposerTest(unittest.TestCase):
    def test_composes_single_series_line_chart(
        self,
    ) -> None:
        facts = TrendOverviewFacts(
            start_date="2025-03-31",
            end_date="2026-03-31",
            grain="quarter",
            series=[
                TrendSeries(
                    institution=InstitutionRef(
                        institution_id="ORG004",
                        institution_name=(
                            "江苏省D市农商行"
                        ),
                    ),
                    metric=MetricRef(
                        metric_id="ZB001",
                        metric_name="各项存款余额",
                        unit="亿元",
                        performance_direction=(
                            "higher_is_better"
                        ),
                    ),
                    points=[
                        TrendPoint(
                            data_date="2025-03-31",
                            value=50.25,
                        ),
                        TrendPoint(
                            data_date="2025-06-30",
                            value=51.80,
                        ),
                        TrendPoint(
                            data_date="2025-09-30",
                            value=52.10,
                        ),
                        TrendPoint(
                            data_date="2025-12-31",
                            value=53.40,
                        ),
                        TrendPoint(
                            data_date="2026-03-31",
                            value=54.20,
                        ),
                    ],
                )
            ],
        )

        answer = DeterministicAnswerComposer().compose(
            question=(
                "分析江苏省D市农商行的"
                "各项存款余额逐季变化。"
            ),
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.answer_type,
            "trend",
        )
        self.assertIn(
            "总体上升",
            answer.headline,
        )
        self.assertIn(
            "累计增加3.95亿元",
            answer.summary,
        )

        self.assertEqual(
            answer.key_metrics,
            [],
        )

        self.assertIsNotNone(answer.table)
        assert answer.table is not None

        self.assertEqual(
            answer.table.columns,
            [
                "日期",
                "各项存款余额",
                "单位",
            ],
        )
        self.assertEqual(
            len(answer.table.rows),
            5,
        )

        self.assertIsNotNone(
            answer.chart_spec
        )
        assert answer.chart_spec is not None

        self.assertEqual(
            answer.chart_spec.chart_type,
            "line",
        )
        self.assertEqual(
            answer.chart_spec.categories,
            [
                "2025-03-31",
                "2025-06-30",
                "2025-09-30",
                "2025-12-31",
                "2026-03-31",
            ],
        )
        self.assertEqual(
            answer.chart_spec.series[0].values,
            [
                50.25,
                51.8,
                52.1,
                53.4,
                54.2,
            ],
        )
        self.assertEqual(
            answer.chart_spec.unit,
            "亿元",
        )


if __name__ == "__main__":
    unittest.main()
