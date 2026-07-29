from __future__ import annotations

import unittest

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.application.answer_models import (
    DirectMetricValueFact,
    DirectMetricValuesFacts,
    InstitutionRef,
)


class DirectMetricAnswerComposerTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.subject = InstitutionRef(
            institution_id="ORG009",
            institution_name="江苏省I市农商行",
        )
        self.composer = (
            DeterministicAnswerComposer()
        )

    def test_composes_single_metric_value(
        self,
    ) -> None:
        facts = DirectMetricValuesFacts(
            subject=self.subject,
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

        answer = self.composer.compose(
            question=(
                "江苏省I市农商行在"
                "2025-11-30的不良贷款率"
                "是多少？"
            ),
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.answer_type,
            "direct_metric_values",
        )
        self.assertEqual(
            answer.headline,
            "江苏省I市农商行不良贷款率",
        )
        self.assertIn(
            "不良贷款率为1.18%",
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
                "指标",
                "数值",
                "单位",
            ],
        )
        self.assertEqual(
            answer.table.rows,
            [
                [
                    "不良贷款率",
                    "1.18",
                    "%",
                ]
            ],
        )

    def test_composes_multiple_metrics_without_chart(
        self,
    ) -> None:
        facts = DirectMetricValuesFacts(
            subject=self.subject,
            period="2025-11-30",
            metrics=[
                DirectMetricValueFact(
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    value=1.18,
                    unit="%",
                ),
                DirectMetricValueFact(
                    metric_id="ZB015",
                    metric_name="拨备覆盖率",
                    value=184.26,
                    unit="%",
                ),
            ],
        )

        answer = self.composer.compose(
            question=(
                "江苏省I市农商行在"
                "2025-11-30的不良贷款率"
                "和拨备覆盖率分别是多少？"
            ),
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.headline,
            "江苏省I市农商行2项指标值",
        )
        self.assertIn(
            "不良贷款率为1.18%",
            answer.summary,
        )
        self.assertIn(
            "拨备覆盖率为184.26%",
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
            answer.table.rows,
            [
                [
                    "不良贷款率",
                    "1.18",
                    "%",
                ],
                [
                    "拨备覆盖率",
                    "184.26",
                    "%",
                ],
            ],
        )

    def test_rejects_duplicate_metrics(
        self,
    ) -> None:
        facts = DirectMetricValuesFacts(
            subject=self.subject,
            period="2025-11-30",
            metrics=[
                DirectMetricValueFact(
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    value=1.18,
                    unit="%",
                ),
                DirectMetricValueFact(
                    metric_id="ZB013",
                    metric_name="不良贷款率",
                    value=1.18,
                    unit="%",
                ),
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "重复指标",
        ):
            self.composer.compose(
                question="测试",
                query_plan={},
                facts=facts,
            )


if __name__ == "__main__":
    unittest.main()
