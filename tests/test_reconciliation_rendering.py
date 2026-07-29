import unittest
from decimal import Decimal

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)


class ReconciliationRenderingTest(unittest.TestCase):
    def test_summary_preserves_component_values(self):
        executor = DeterministicQueryPlanExecutor(None)

        total = ExecutionValue(
            kind="records",
            data=[{
                "metric_name": "各项存款余额",
                "value": Decimal("116.98"),
                "unit": "亿元",
            }],
            unit="亿元",
        )
        component_sum = ExecutionValue(
            kind="scalar",
            data={
                "operation": "sum",
                "value": Decimal("116.98"),
                "left_record": {
                    "metric_name": "对公存款余额",
                    "value": Decimal("42.32"),
                    "unit": "亿元",
                },
                "right_record": {
                    "metric_name": "个人存款余额",
                    "value": Decimal("74.66"),
                    "unit": "亿元",
                },
            },
            unit="亿元",
        )

        result = executor._op_reconcile(
            [total, component_sum],
            {},
        )
        _, _, summary = executor._render(
            result,
            {
                "rounding": {
                    "mode": "final_only",
                    "digits": 2,
                }
            },
        )

        self.assertIn("42.32亿元", summary)
        self.assertIn("74.66亿元", summary)
        self.assertEqual(
            summary.count("116.98亿元"),
            2,
        )
        self.assertIn("差额为0.0亿元", summary)


if __name__ == "__main__":
    unittest.main()
