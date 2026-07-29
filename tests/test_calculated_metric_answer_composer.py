from __future__ import annotations

import unittest

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.application.answer_models import (
    CalculatedMetricFacts,
    CalculationInputFact,
    InstitutionRef,
)


class CalculatedMetricAnswerComposerTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.composer = (
            DeterministicAnswerComposer()
        )
        self.subject = InstitutionRef(
            institution_id="ORG004",
            institution_name=(
                "江苏省D市农商行"
            ),
        )

    def test_composes_positive_growth_rate(
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

        answer = self.composer.compose(
            question="测试增长率",
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.answer_type,
            "calculated_metric",
        )
        self.assertEqual(
            answer.headline,
            (
                "江苏省D市农商行"
                "各项存款余额增长0.33%"
            ),
        )
        self.assertIn(
            "由55.00亿元变为55.18亿元",
            answer.summary,
        )
        self.assertEqual(
            len(answer.key_metrics),
            1,
        )
        self.assertEqual(
            answer.key_metrics[0].value,
            0.3273,
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
                "项目",
                "指标",
                "期间",
                "数值",
                "单位",
            ],
        )
        self.assertEqual(
            len(answer.table.rows),
            3,
        )

    def test_composes_negative_percentage_point_change(
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

        answer = self.composer.compose(
            question="测试百分点变化",
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.headline,
            (
                "江苏省D市农商行"
                "不良贷款率下降0.08个百分点"
            ),
        )
        self.assertIn(
            "由1.18%变为1.10%",
            answer.summary,
        )
        self.assertIsNone(
            answer.chart_spec
        )

    def test_composes_ratio(
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
            result_value=1.17994,
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

        answer = self.composer.compose(
            question="测试比率",
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.headline,
            (
                "江苏省I市农商行"
                "不良贷款率为1.18%"
            ),
        )
        self.assertIn(
            "不良贷款余额为0.72亿元",
            answer.summary,
        )
        self.assertIn(
            "各项贷款余额为61.02亿元",
            answer.summary,
        )
        self.assertEqual(
            answer.key_metrics[0].label,
            "不良贷款率",
        )
        self.assertEqual(
            answer.key_metrics[0].value,
            1.17994,
        )
        self.assertIsNone(
            answer.chart_spec
        )

    def test_rejects_unknown_calculation_type(
        self,
    ) -> None:
        facts = CalculatedMetricFacts(
            subject=self.subject,
            calculation_type="unknown",
            result_metric_id=None,
            result_metric_name="未知结果",
            result_value=1,
            result_unit="亿元",
            inputs=[
                CalculationInputFact(
                    role="left",
                    metric_id="ZB001",
                    metric_name="指标一",
                    period="2025-12-31",
                    value=2,
                    unit="亿元",
                ),
                CalculationInputFact(
                    role="right",
                    metric_id="ZB001",
                    metric_name="指标一",
                    period="2024-12-31",
                    value=1,
                    unit="亿元",
                ),
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "不支持的派生计算类型",
        ):
            self.composer.compose(
                question="测试",
                query_plan={},
                facts=facts,
            )


if __name__ == "__main__":
    unittest.main()
