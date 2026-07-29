from __future__ import annotations

import unittest

from app.application.answer_models import (
    CalculatedMetricFacts,
    CalculationInputFact,
    InstitutionRef,
)


class CalculatedMetricAnswerModelsTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.subject = InstitutionRef(
            institution_id="ORG004",
            institution_name="江苏省D市农商行",
        )

    def test_supports_growth_rate(
        self,
    ) -> None:
        facts = CalculatedMetricFacts(
            subject=self.subject,
            calculation_type="growth_rate",
            result_metric_id=None,
            result_metric_name=(
                "各项存款余额增长率"
            ),
            result_value=0.3273,
            result_unit="%",
            inputs=[
                CalculationInputFact(
                    role="current",
                    metric_id="ZB001",
                    metric_name="各项存款余额",
                    period="2026-03-31",
                    value=55.18,
                    unit="亿元",
                ),
                CalculationInputFact(
                    role="base",
                    metric_id="ZB001",
                    metric_name="各项存款余额",
                    period="2025-03-31",
                    value=55.00,
                    unit="亿元",
                ),
            ],
        )

        self.assertEqual(
            facts.answer_type,
            "calculated_metric",
        )
        self.assertEqual(
            facts.calculation_type,
            "growth_rate",
        )
        self.assertEqual(
            facts.result_unit,
            "%",
        )
        self.assertEqual(
            [
                item.role
                for item in facts.inputs
            ],
            [
                "current",
                "base",
            ],
        )

    def test_supports_ratio_between_metrics(
        self,
    ) -> None:
        facts = CalculatedMetricFacts(
            subject=InstitutionRef(
                institution_id="ORG009",
                institution_name=(
                    "江苏省I市农商行"
                ),
            ),
            calculation_type="ratio",
            result_metric_id="ZB013",
            result_metric_name="不良贷款率",
            result_value=1.18,
            result_unit="%",
            inputs=[
                CalculationInputFact(
                    role="numerator",
                    metric_id="ZB014",
                    metric_name="不良贷款余额",
                    period="2025-11-30",
                    value=0.72,
                    unit="亿元",
                ),
                CalculationInputFact(
                    role="denominator",
                    metric_id="ZB002",
                    metric_name="各项贷款余额",
                    period="2025-11-30",
                    value=61.02,
                    unit="亿元",
                ),
            ],
        )

        self.assertEqual(
            facts.result_metric_id,
            "ZB013",
        )
        self.assertEqual(
            facts.result_metric_name,
            "不良贷款率",
        )
        self.assertEqual(
            len(facts.inputs),
            2,
        )
        self.assertEqual(
            facts.inputs[0].role,
            "numerator",
        )
        self.assertEqual(
            facts.inputs[1].role,
            "denominator",
        )

    def test_supports_percentage_point_change(
        self,
    ) -> None:
        facts = CalculatedMetricFacts(
            subject=self.subject,
            calculation_type=(
                "percentage_point_change"
            ),
            result_metric_id=None,
            result_metric_name=(
                "不良贷款率变化"
            ),
            result_value=-0.08,
            result_unit="百分点",
            inputs=[
                CalculationInputFact(
                    role="current",
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    period="2026-03-31",
                    value=1.10,
                    unit="%",
                ),
                CalculationInputFact(
                    role="base",
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    period="2025-12-31",
                    value=1.18,
                    unit="%",
                ),
            ],
        )

        self.assertEqual(
            facts.result_value,
            -0.08,
        )
        self.assertEqual(
            facts.result_unit,
            "百分点",
        )


if __name__ == "__main__":
    unittest.main()
