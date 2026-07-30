from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    TrendOverviewFacts,
)


class TrendFactExtractionTest(unittest.TestCase):
    def test_extracts_and_orders_multiple_series(
        self,
    ) -> None:
        plan = {
            "time": {
                "mode": "range",
                "dates": [],
                "start_date": "2025-03-31",
                "end_date": "2025-09-30",
                "grain": "quarter",
                "comparison_periods": [],
            }
        }

        records = [
            {
                "institution_id": "ORG004",
                "institution_name": (
                    "江苏省D市农商行"
                ),
                "date": "2025-09-30",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("52.10"),
            },
            {
                "institution_id": "ORG004",
                "institution_name": (
                    "江苏省D市农商行"
                ),
                "date": "2025-03-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("50.25"),
            },
            {
                "institution_id": "ORG004",
                "institution_name": (
                    "江苏省D市农商行"
                ),
                "date": "2025-06-30",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("51.80"),
            },
            {
                "institution_id": "ORG005",
                "institution_name": (
                    "江苏省E市农商行"
                ),
                "date": "2025-03-31",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("48.10"),
            },
            {
                "institution_id": "ORG005",
                "institution_name": (
                    "江苏省E市农商行"
                ),
                "date": "2025-06-30",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("48.90"),
            },
            {
                "institution_id": "ORG005",
                "institution_name": (
                    "江苏省E市农商行"
                ),
                "date": "2025-09-30",
                "metric_id": "ZB001",
                "metric_name": "各项存款余额",
                "unit": "亿元",
                "value": Decimal("49.40"),
            },
        ]

        final_value = ExecutionValue(
            kind="trend",
            data={
                "series": records,
                "trends": [
                    {
                        "institution_id": "ORG004",
                        "metric_id": "ZB001",
                        "trend": "increasing",
                    },
                    {
                        "institution_id": "ORG005",
                        "metric_id": "ZB001",
                        "trend": "increasing",
                    },
                ],
            },
            unit="亿元",
        )

        facts = (
            DeterministicQueryPlanExecutor
            ._trend_overview_facts(
                plan,
                final_value,
            )
        )

        self.assertIsInstance(
            facts,
            TrendOverviewFacts,
        )
        assert facts is not None

        self.assertEqual(
            facts.start_date,
            "2025-03-31",
        )
        self.assertEqual(
            facts.end_date,
            "2025-09-30",
        )
        self.assertEqual(
            facts.grain,
            "quarter",
        )
        self.assertEqual(
            len(facts.series),
            2,
        )

        first_series = facts.series[0]

        self.assertEqual(
            first_series.institution.institution_id,
            "ORG004",
        )
        self.assertEqual(
            first_series.metric.metric_id,
            "ZB001",
        )
        self.assertEqual(
            first_series.metric.unit,
            "亿元",
        )
        self.assertEqual(
            [
                point.data_date
                for point in first_series.points
            ],
            [
                "2025-03-31",
                "2025-06-30",
                "2025-09-30",
            ],
        )
        self.assertEqual(
            [
                point.value
                for point in first_series.points
            ],
            [
                50.25,
                51.8,
                52.1,
            ],
        )


if __name__ == "__main__":
    unittest.main()
