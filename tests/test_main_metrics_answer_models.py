from __future__ import annotations

import unittest

from app.application.answer_models import (
    InstitutionRef,
    MainMetricFact,
    MainMetricsOverviewFacts,
)


class MainMetricsAnswerModelsTest(unittest.TestCase):
    def test_builds_main_metrics_overview_facts(
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
                    rank=3,
                    performance_direction=(
                        "higher_is_better"
                    ),
                    performance_band="better",
                ),
                MainMetricFact(
                    metric_id="ZB022",
                    metric_name="存贷比",
                    value=76.2,
                    unit="%",
                    rank=5,
                    performance_direction=None,
                    performance_band="numeric_only",
                ),
            ],
        )

        self.assertEqual(
            facts.answer_type,
            "main_metrics_overview",
        )
        self.assertEqual(
            facts.subject.institution_id,
            "ORG007",
        )
        self.assertEqual(len(facts.metrics), 2)
        self.assertEqual(
            facts.metrics[0].performance_band,
            "better",
        )
        self.assertIsNone(
            facts.metrics[1].performance_direction
        )


if __name__ == "__main__":
    unittest.main()
