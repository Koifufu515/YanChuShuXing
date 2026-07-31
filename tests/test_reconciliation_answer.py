from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    ReconciliationFacts,
)


class ReconciliationAnswerTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.executor = (
            DeterministicQueryPlanExecutor(None)
        )
        self.composer = (
            DeterministicAnswerComposer()
        )

        self.corporate_record = {
            "institution_id": "ORG003",
            "institution_name": (
                "江苏省C市农商行"
            ),
            "date": "2025-12-31",
            "metric_id": "ZB003",
            "metric_name": "对公存款余额",
            "unit": "亿元",
            "value": Decimal("42.32"),
        }
        self.personal_record = {
            "institution_id": "ORG003",
            "institution_name": (
                "江苏省C市农商行"
            ),
            "date": "2025-12-31",
            "metric_id": "ZB004",
            "metric_name": "个人存款余额",
            "unit": "亿元",
            "value": Decimal("74.66"),
        }
        self.total_record = {
            "institution_id": "ORG003",
            "institution_name": (
                "江苏省C市农商行"
            ),
            "date": "2025-12-31",
            "metric_id": "ZB001",
            "metric_name": "各项存款余额",
            "unit": "亿元",
            "value": Decimal("116.98"),
        }

    def _facts(
        self,
    ) -> ReconciliationFacts:
        total = ExecutionValue(
            kind="records",
            data=[self.total_record],
            unit="亿元",
        )
        component_sum = ExecutionValue(
            kind="scalar",
            data={
                "operation": "sum",
                "value": Decimal("116.98"),
                "left_record": (
                    self.corporate_record
                ),
                "right_record": (
                    self.personal_record
                ),
            },
            unit="亿元",
        )

        final_value = (
            self.executor._op_reconcile(
                [
                    total,
                    component_sum,
                ],
                {},
            )
        )
        final_value.operator_id = "OP005"

        query_plan = {
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP005",
                    "input_refs": [
                        "total_deposit",
                        "sum_deposit",
                    ],
                    "output_ref": (
                        "check_result"
                    ),
                    "parameters": {},
                }
            ]
        }

        facts = (
            self.executor
            ._reconciliation_facts(
                query_plan,
                {
                    "total_deposit": total,
                    "sum_deposit": (
                        component_sum
                    ),
                    "check_result": (
                        final_value
                    ),
                },
            )
        )

        self.assertIsInstance(
            facts,
            ReconciliationFacts,
        )
        assert isinstance(
            facts,
            ReconciliationFacts,
        )
        return facts

    def test_extracts_reconciliation_facts(
        self,
    ) -> None:
        facts = self._facts()

        self.assertEqual(
            facts.subject.institution_id,
            "ORG003",
        )
        self.assertEqual(
            facts.period,
            "2025-12-31",
        )
        self.assertEqual(
            facts.total_metric_name,
            "各项存款余额",
        )
        self.assertEqual(
            len(facts.components),
            2,
        )
        self.assertTrue(facts.is_equal)
        self.assertAlmostEqual(
            float(facts.difference),
            0.0,
        )
        self.assertEqual(
            facts.answer_type,
            "reconciliation",
        )

    def test_composes_complete_answer(
        self,
    ) -> None:
        facts = self._facts()

        answer = self.composer.compose(
            question="测试对账",
            query_plan={},
            facts=facts,
        )

        self.assertEqual(
            answer.answer_type,
            "reconciliation",
        )
        self.assertEqual(
            answer.headline,
            (
                "江苏省C市农商行"
                "各项存款余额对账一致"
            ),
        )

        for expected in (
            "对公存款余额42.32亿元",
            "个人存款余额74.66亿元",
            "116.98亿元",
            "差额为0.00亿元",
        ):
            self.assertIn(
                expected,
                answer.summary,
            )

        self.assertEqual(
            len(answer.key_metrics),
            3,
        )
        self.assertIsNotNone(
            answer.table
        )
        assert answer.table is not None
        self.assertEqual(
            answer.table.columns,
            [
                "项目",
                "数值",
                "单位",
            ],
        )
        self.assertEqual(
            len(answer.table.rows),
            5,
        )
        self.assertIsNone(
            answer.chart_spec
        )


if __name__ == "__main__":
    unittest.main()
