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
    ExtremeMetricFacts,
    ExtremeMetricItem,
    InstitutionRef,
)


class ExtremeValueAnswerTest(
    unittest.TestCase
):
    def test_extracts_minimum_fact_with_population(
        self,
    ) -> None:
        source_records = [
            {
                "institution_id": "ORG001",
                "institution_name": (
                    "江苏省A市农商行"
                ),
                "date": "2025-12-31",
                "metric_id": "ZB013",
                "metric_name": "不良贷款率",
                "unit": "%",
                "value": Decimal("0.91"),
            },
            {
                "institution_id": "ORG010",
                "institution_name": (
                    "江苏省J市农商行"
                ),
                "date": "2025-12-31",
                "metric_id": "ZB013",
                "metric_name": "不良贷款率",
                "unit": "%",
                "value": Decimal("0.77"),
            },
            {
                "institution_id": "ORG013",
                "institution_name": (
                    "江苏省M市农商行"
                ),
                "date": "2025-12-31",
                "metric_id": "ZB013",
                "metric_name": "不良贷款率",
                "unit": "%",
                "value": Decimal("1.21"),
            },
        ]

        plan = {
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_records",
                    "parameters": {},
                },
                {
                    "step": 2,
                    "operator_id": "OP014",
                    "input_refs": [
                        "npl_records"
                    ],
                    "output_ref": "npl_minimum",
                    "parameters": {
                        "type": "min"
                    },
                },
            ],
        }

        context = {
            "npl_records": ExecutionValue(
                kind="records",
                data=source_records,
                unit="%",
            ),
            "npl_minimum": ExecutionValue(
                kind="records",
                data=[source_records[1]],
                unit="%",
            ),
        }

        facts = (
            DeterministicQueryPlanExecutor
            ._extreme_metric_facts(
                plan,
                context,
            )
        )

        self.assertIsInstance(
            facts,
            ExtremeMetricFacts,
        )
        assert facts is not None

        self.assertEqual(
            facts.extreme_type,
            "min",
        )
        self.assertEqual(
            facts.population_size,
            3,
        )
        self.assertEqual(
            facts.metric_name,
            "不良贷款率",
        )
        self.assertEqual(
            len(facts.items),
            1,
        )
        self.assertEqual(
            facts.items[0]
            .institution.institution_name,
            "江苏省J市农商行",
        )
        self.assertEqual(
            facts.items[0].value,
            0.77,
        )

    def test_minimum_answer_uses_lowest_wording(
        self,
    ) -> None:
        facts = ExtremeMetricFacts(
            metric_id="ZB013",
            metric_name="不良贷款率",
            unit="%",
            period="2025-12-31",
            extreme_type="min",
            population_size=13,
            items=[
                ExtremeMetricItem(
                    institution=InstitutionRef(
                        institution_id="ORG010",
                        institution_name=(
                            "江苏省J市农商行"
                        ),
                    ),
                    value=0.77,
                )
            ],
        )

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "不良贷款率最低的是哪家？"
                ),
                query_plan={},
                facts=facts,
            )
        )

        self.assertEqual(
            answer.answer_type,
            "extreme_value",
        )
        self.assertIn(
            "江苏省J市农商行",
            answer.headline,
        )
        self.assertIn(
            "不良贷款率最低",
            answer.headline,
        )
        self.assertIn(
            "0.77%",
            answer.headline,
        )
        self.assertNotIn(
            "排名第一",
            answer.summary,
        )
        self.assertNotIn(
            "第1名",
            answer.summary,
        )

    def test_maximum_tie_preserves_all_institutions(
        self,
    ) -> None:
        facts = ExtremeMetricFacts(
            metric_id="ZB001",
            metric_name="各项存款余额",
            unit="亿元",
            period="2025-12-31",
            extreme_type="max",
            population_size=13,
            items=[
                ExtremeMetricItem(
                    institution=InstitutionRef(
                        institution_id="ORG001",
                        institution_name=(
                            "江苏省A市农商行"
                        ),
                    ),
                    value=80,
                ),
                ExtremeMetricItem(
                    institution=InstitutionRef(
                        institution_id="ORG002",
                        institution_name=(
                            "江苏省B市农商行"
                        ),
                    ),
                    value=80,
                ),
            ],
        )

        answer = (
            DeterministicAnswerComposer()
            .compose(
                question=(
                    "存款余额最高的是哪家？"
                ),
                query_plan={},
                facts=facts,
            )
        )

        self.assertIn(
            "并列取得",
            answer.headline,
        )
        self.assertIn(
            "江苏省A市农商行",
            answer.summary,
        )
        self.assertIn(
            "江苏省B市农商行",
            answer.summary,
        )
        self.assertIn(
            "并列最高",
            answer.summary,
        )

        self.assertIsNotNone(answer.table)
        assert answer.table is not None
        self.assertEqual(
            len(answer.table.rows),
            2,
        )


if __name__ == "__main__":
    unittest.main()
