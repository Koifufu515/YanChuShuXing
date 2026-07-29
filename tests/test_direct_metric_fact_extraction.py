from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    DirectMetricValuesFacts,
)


def record(
    metric_id: str,
    metric_name: str,
    unit: str,
    value: Decimal,
) -> dict[str, object]:
    return {
        "institution_id": "ORG009",
        "institution_name": "江苏省I市农商行",
        "date": "2025-11-30",
        "metric_id": metric_id,
        "metric_name": metric_name,
        "unit": unit,
        "value": value,
    }


def base_plan(
    operations: list[dict[str, object]],
    requested_metric_ids: list[str],
) -> dict[str, object]:
    return {
        "institutions": {
            "targets": [
                {
                    "institution_id": "ORG009",
                    "institution_name": (
                        "江苏省I市农商行"
                    ),
                }
            ],
            "comparison_population": {
                "type": "none",
                "institution_ids": [],
            },
        },
        "metrics": {
            "requested_metric_ids": (
                requested_metric_ids
            ),
            "source_metric_ids": (
                requested_metric_ids
            ),
            "concept_ids": [],
        },
        "time": {
            "mode": "point",
            "dates": ["2025-11-30"],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        },
        "operations": operations,
    }


class DirectMetricFactExtractionTest(
    unittest.TestCase
):
    def test_extracts_single_direct_metric(
        self,
    ) -> None:
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_rate",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                }
            ],
            requested_metric_ids=["ZB013"],
        )

        context = {
            "npl_rate": ExecutionValue(
                kind="records",
                data=[
                    record(
                        "ZB013",
                        "不良贷款率",
                        "%",
                        Decimal("1.18"),
                    )
                ],
                unit="%",
            )
        }

        facts = (
            DeterministicQueryPlanExecutor
            ._direct_metric_values_facts(
                plan,
                context,
            )
        )

        self.assertIsInstance(
            facts,
            DirectMetricValuesFacts,
        )
        assert facts is not None

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
        self.assertEqual(
            facts.metrics[0].value,
            1.18,
        )

    def test_extracts_multiple_metrics_in_requested_order(
        self,
    ) -> None:
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "npl_rate",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB015"],
                    "output_ref": "coverage_rate",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP019",
                    "input_refs": [
                        "coverage_rate",
                        "npl_rate",
                    ],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            requested_metric_ids=[
                "ZB013",
                "ZB015",
            ],
        )

        context = {
            "npl_rate": ExecutionValue(
                kind="records",
                data=[
                    record(
                        "ZB013",
                        "不良贷款率",
                        "%",
                        Decimal("1.18"),
                    )
                ],
                unit="%",
            ),
            "coverage_rate": ExecutionValue(
                kind="records",
                data=[
                    record(
                        "ZB015",
                        "拨备覆盖率",
                        "%",
                        Decimal("184.26"),
                    )
                ],
                unit="%",
            ),
            "final_result": ExecutionValue(
                kind="composite",
                data={"items": []},
                unit=None,
            ),
        }

        facts = (
            DeterministicQueryPlanExecutor
            ._direct_metric_values_facts(
                plan,
                context,
            )
        )

        self.assertIsInstance(
            facts,
            DirectMetricValuesFacts,
        )
        assert facts is not None

        self.assertEqual(
            [
                metric.metric_id
                for metric in facts.metrics
            ],
            [
                "ZB013",
                "ZB015",
            ],
        )
        self.assertEqual(
            [
                metric.value
                for metric in facts.metrics
            ],
            [
                1.18,
                184.26,
            ],
        )

    def test_rejects_computed_merge_result(
        self,
    ) -> None:
        plan = base_plan(
            operations=[
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB014"],
                    "output_ref": "npl_balance",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB002"],
                    "output_ref": "loan_balance",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP006",
                    "input_refs": [
                        "npl_balance",
                        "loan_balance",
                    ],
                    "output_ref": "calculated_rate",
                    "parameters": {
                        "result_metric_id": "ZB013",
                        "result_metric_name": (
                            "不良贷款率"
                        ),
                        "result_unit": "%",
                        "multiplier": 100,
                    },
                },
                {
                    "step": 4,
                    "operator_id": "OP019",
                    "input_refs": [
                        "npl_balance",
                        "calculated_rate",
                    ],
                    "output_ref": "final_result",
                    "parameters": {},
                },
            ],
            requested_metric_ids=[
                "ZB014",
                "ZB013",
            ],
        )

        facts = (
            DeterministicQueryPlanExecutor
            ._direct_metric_values_facts(
                plan,
                context={},
            )
        )

        self.assertIsNone(facts)


if __name__ == "__main__":
    unittest.main()
