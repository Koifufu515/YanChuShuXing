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


class TwoInstitutionComparisonAnswerTest(
    unittest.TestCase
):
    def test_same_metric_two_institutions_keep_names(
        self,
    ) -> None:
        plan = {
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "l_value",
                    "parameters": {
                        "institution_id": "ORG012",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "j_value",
                    "parameters": {
                        "institution_id": "ORG010",
                        "date": "2026-02-28",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP003",
                    "input_refs": [
                        "l_value",
                        "j_value",
                    ],
                    "output_ref": "difference",
                    "parameters": {},
                },
            ]
        }

        context = {
            "l_value": ExecutionValue(
                kind="records",
                data=[
                    {
                        "institution_id": "ORG012",
                        "institution_name": (
                            "江苏省L市农商行"
                        ),
                        "date": "2026-02-28",
                        "metric_id": "ZB013",
                        "metric_name": "不良贷款率",
                        "value": Decimal("0.89"),
                        "unit": "%",
                    }
                ],
            ),
            "j_value": ExecutionValue(
                kind="records",
                data=[
                    {
                        "institution_id": "ORG010",
                        "institution_name": (
                            "江苏省J市农商行"
                        ),
                        "date": "2026-02-28",
                        "metric_id": "ZB013",
                        "metric_name": "不良贷款率",
                        "value": Decimal("0.77"),
                        "unit": "%",
                    }
                ],
            ),
            "difference": ExecutionValue(
                kind="scalar",
                data={
                    "value": Decimal("0.12"),
                    "operation": "difference",
                },
                unit="%",
                operator_id="OP003",
                metadata={
                    "operation": "difference",
                },
            ),
        }

        facts = (
            DeterministicQueryPlanExecutor
            ._calculated_metric_facts(
                plan,
                context,
            )
        )

        self.assertIsNotNone(facts)
        assert facts is not None

        self.assertIsNone(
            facts.subject.institution_id
        )
        self.assertEqual(
            facts.result_unit,
            "百分点",
        )
        self.assertEqual(
            [
                item.institution.institution_name
                for item in facts.inputs
                if item.institution is not None
            ],
            [
                "江苏省L市农商行",
                "江苏省J市农商行",
            ],
        )

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "J市和L市谁的不良率更低？"
                ),
                query_plan=plan,
                facts=facts,
            )
        )

        self.assertEqual(
            answer.headline,
            (
                "江苏省L市农商行不良贷款率"
                "高于江苏省J市农商行"
                "0.12个百分点"
            ),
        )
        self.assertIn(
            (
                "江苏省J市农商行的不良贷款率"
                "更低，江苏省L市农商行更高"
            ),
            answer.summary,
        )
        self.assertIn(
            "相差0.12个百分点",
            answer.summary,
        )

        self.assertIsNotNone(answer.table)
        assert answer.table is not None

        self.assertEqual(
            [
                row[0]
                for row in answer.table.rows[:2]
            ],
            [
                "江苏省L市农商行",
                "江苏省J市农商行",
            ],
        )


if __name__ == "__main__":
    unittest.main()
