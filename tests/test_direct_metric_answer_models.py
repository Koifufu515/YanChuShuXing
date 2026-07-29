from __future__ import annotations

import unittest

from app.application.answer_models import (
    DirectMetricValueFact,
    DirectMetricValuesFacts,
    InstitutionRef,
)


class DirectMetricAnswerModelsTest(
    unittest.TestCase
):
    def test_supports_single_metric_value(
        self,
    ) -> None:
        facts = DirectMetricValuesFacts(
            subject=InstitutionRef(
                institution_id="ORG009",
                institution_name=(
                    "江苏省I市农商行"
                ),
            ),
            period="2025-11-30",
            metrics=[
                DirectMetricValueFact(
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    value=1.18,
                    unit="%",
                )
            ],
        )

        self.assertEqual(
            facts.answer_type,
            "direct_metric_values",
        )
        self.assertEqual(
            facts.subject.institution_id,
            "ORG009",
        )
        self.assertEqual(
            facts.period,
            "2025-11-30",
        )
        self.assertEqual(
            len(facts.metrics),
            1,
        )
        self.assertEqual(
            facts.metrics[0].metric_id,
            "ZB013",
        )

    def test_supports_multiple_metrics_with_mixed_units(
        self,
    ) -> None:
        facts = DirectMetricValuesFacts(
            subject=InstitutionRef(
                institution_id="ORG009",
                institution_name=(
                    "江苏省I市农商行"
                ),
            ),
            period="2025-11-30",
            metrics=[
                DirectMetricValueFact(
                    metric_id="ZB002",
                    metric_name="各项贷款余额",
                    value=61.42,
                    unit="亿元",
                ),
                DirectMetricValueFact(
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    value=1.18,
                    unit="%",
                ),
                DirectMetricValueFact(
                    metric_id="ZB011",
                    metric_name="净利润",
                    value=176.25,
                    unit="万元",
                ),
            ],
        )

        self.assertEqual(
            [
                metric.metric_id
                for metric in facts.metrics
            ],
            [
                "ZB002",
                "ZB013",
                "ZB011",
            ],
        )
        self.assertEqual(
            {
                metric.unit
                for metric in facts.metrics
            },
            {
                "亿元",
                "%",
                "万元",
            },
        )


if __name__ == "__main__":
    unittest.main()
