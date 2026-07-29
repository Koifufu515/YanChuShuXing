from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    CalculatedMetricFacts,
)


def metric_record(
    *,
    institution_id: str,
    institution_name: str,
    data_date: str,
    metric_id: str,
    metric_name: str,
    unit: str,
    value: str,
) -> dict[str, object]:
    return {
        "institution_id": institution_id,
        "institution_name": institution_name,
        "date": data_date,
        "metric_id": metric_id,
        "metric_name": metric_name,
        "unit": unit,
        "value": Decimal(value),
    }


class CalculatedMetricFactExtractionTest(
    unittest.TestCase
):
    def test_extracts_growth_rate(
        self,
    ) -> None:
        current = metric_record(
            institution_id="ORG004",
            institution_name=(
                "江苏省D市农商行"
            ),
            data_date="2026-03-31",
            metric_id="ZB001",
            metric_name="各项存款余额",
            unit="亿元",
            value="55.18",
        )
        base = metric_record(
            institution_id="ORG004",
            institution_name=(
                "江苏省D市农商行"
            ),
            data_date="2025-03-31",
            metric_id="ZB001",
            metric_name="各项存款余额",
            unit="亿元",
            value="55.00",
        )

        plan = {
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "current_value",
                    "parameters": {
                        "institution_id": "ORG004",
                        "date": "2026-03-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "base_value",
                    "parameters": {
                        "institution_id": "ORG004",
                        "date": "2025-03-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP007",
                    "input_refs": [
                        "current_value",
                        "base_value",
                    ],
                    "output_ref": "growth_result",
                    "parameters": {},
                },
            ],
        }

        context = {
            "current_value": ExecutionValue(
                kind="records",
                data=[current],
                unit="亿元",
            ),
            "base_value": ExecutionValue(
                kind="records",
                data=[base],
                unit="亿元",
            ),
            "growth_result": ExecutionValue(
                kind="scalar",
                data={
                    "value": Decimal(
                        "0.3272727273"
                    ),
                    "left_value": Decimal(
                        "55.18"
                    ),
                    "right_value": Decimal(
                        "55.00"
                    ),
                    "operation": "growth_rate",
                    "left_record": current,
                    "right_record": base,
                },
                unit="%",
                metadata={
                    "operation": "growth_rate",
                    "metric_id": None,
                    "metric_name": None,
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

        self.assertIsInstance(
            facts,
            CalculatedMetricFacts,
        )
        assert facts is not None

        self.assertEqual(
            facts.calculation_type,
            "growth_rate",
        )
        self.assertEqual(
            facts.result_metric_name,
            "各项存款余额增长率",
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
        self.assertEqual(
            facts.inputs[0].period,
            "2026-03-31",
        )
        self.assertEqual(
            facts.inputs[1].period,
            "2025-03-31",
        )

    def test_extracts_ratio_with_result_metadata(
        self,
    ) -> None:
        numerator = metric_record(
            institution_id="ORG009",
            institution_name=(
                "江苏省I市农商行"
            ),
            data_date="2025-11-30",
            metric_id="ZB014",
            metric_name="不良贷款余额",
            unit="亿元",
            value="0.72",
        )
        denominator = metric_record(
            institution_id="ORG009",
            institution_name=(
                "江苏省I市农商行"
            ),
            data_date="2025-11-30",
            metric_id="ZB002",
            metric_name="各项贷款余额",
            unit="亿元",
            value="61.02",
        )

        plan = {
            "operations": [
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
                    "output_ref": "npl_rate",
                    "parameters": {
                        "result_metric_id": "ZB013",
                        "result_metric_name": (
                            "不良贷款率"
                        ),
                        "result_unit": "%",
                        "multiplier": 100,
                    },
                },
            ],
        }

        context = {
            "npl_balance": ExecutionValue(
                kind="records",
                data=[numerator],
                unit="亿元",
            ),
            "loan_balance": ExecutionValue(
                kind="records",
                data=[denominator],
                unit="亿元",
            ),
            "npl_rate": ExecutionValue(
                kind="scalar",
                data={
                    "value": Decimal(
                        "1.179940"
                    ),
                    "left_value": Decimal(
                        "0.72"
                    ),
                    "right_value": Decimal(
                        "61.02"
                    ),
                    "operation": "ratio",
                    "left_record": numerator,
                    "right_record": denominator,
                },
                unit="%",
                metadata={
                    "operation": "ratio",
                    "metric_id": "ZB013",
                    "metric_name": "不良贷款率",
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

        self.assertIsInstance(
            facts,
            CalculatedMetricFacts,
        )
        assert facts is not None

        self.assertEqual(
            facts.calculation_type,
            "ratio",
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
            [
                item.role
                for item in facts.inputs
            ],
            [
                "numerator",
                "denominator",
            ],
        )

    def test_rejects_province_average_lineage(
        self,
    ) -> None:
        plan = {
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "target_value",
                    "parameters": {
                        "institution_id": "ORG009",
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB013"],
                    "output_ref": "province_values",
                    "parameters": {
                        "institution_ids": [
                            "ORG001",
                            "ORG002",
                        ],
                        "date": "2025-11-30",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP010",
                    "input_refs": [
                        "province_values"
                    ],
                    "output_ref": "province_average",
                    "parameters": {},
                },
                {
                    "step": 4,
                    "operator_id": "OP003",
                    "input_refs": [
                        "target_value",
                        "province_average",
                    ],
                    "output_ref": "difference",
                    "parameters": {},
                },
            ],
        }

        facts = (
            DeterministicQueryPlanExecutor
            ._calculated_metric_facts(
                plan,
                context={},
            )
        )

        self.assertIsNone(facts)

    def test_rejects_multi_record_inputs(
        self,
    ) -> None:
        record_one = metric_record(
            institution_id="ORG004",
            institution_name=(
                "江苏省D市农商行"
            ),
            data_date="2025-03-31",
            metric_id="ZB001",
            metric_name="各项存款余额",
            unit="亿元",
            value="55.00",
        )
        record_two = dict(record_one)
        record_two["date"] = "2025-06-30"

        plan = {
            "operations": [
                {
                    "step": 1,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "left_values",
                    "parameters": {
                        "institution_id": "ORG004",
                        "date": "2025-03-31",
                    },
                },
                {
                    "step": 2,
                    "operator_id": "OP001",
                    "input_refs": ["ZB001"],
                    "output_ref": "right_value",
                    "parameters": {
                        "institution_id": "ORG004",
                        "date": "2025-03-31",
                    },
                },
                {
                    "step": 3,
                    "operator_id": "OP003",
                    "input_refs": [
                        "left_values",
                        "right_value",
                    ],
                    "output_ref": "difference",
                    "parameters": {},
                },
            ],
        }

        context = {
            "left_values": ExecutionValue(
                kind="records",
                data=[
                    record_one,
                    record_two,
                ],
                unit="亿元",
            ),
            "right_value": ExecutionValue(
                kind="records",
                data=[record_one],
                unit="亿元",
            ),
            "difference": ExecutionValue(
                kind="scalar",
                data={
                    "value": Decimal("0"),
                    "operation": "difference",
                },
                unit="亿元",
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

        self.assertIsNone(facts)


if __name__ == "__main__":
    unittest.main()
