from __future__ import annotations

import unittest

from app.application.answer_models import (
    InstitutionRef,
    MetricRef,
    TrendOverviewFacts,
    TrendPoint,
    TrendSeries,
)


class TrendAnswerModelsTest(unittest.TestCase):
    def test_builds_single_metric_trend_facts(
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

        self.assertEqual(
            facts.answer_type,
            "trend",
        )
        self.assertEqual(
            facts.grain,
            "quarter",
        )
        self.assertEqual(
            len(facts.series),
            1,
        )
        self.assertEqual(
            len(facts.series[0].points),
            5,
        )
        self.assertEqual(
            facts.series[0].metric.metric_id,
            "ZB001",
        )
        self.assertEqual(
            facts.series[0].points[0].data_date,
            "2025-03-31",
        )
        self.assertEqual(
            facts.series[0].points[-1].data_date,
            "2026-03-31",
        )


if __name__ == "__main__":
    unittest.main()
