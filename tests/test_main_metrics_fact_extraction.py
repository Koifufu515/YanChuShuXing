from __future__ import annotations

import unittest
from decimal import Decimal

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.answer_models import (
    MainMetricsOverviewFacts,
)


class MainMetricsFactExtractionTest(unittest.TestCase):
    def test_extracts_target_values_ranks_and_bands(
        self,
    ) -> None:
        metric_ids = [
            "ZB001",
            "ZB002",
            "ZB022",
            "ZB013",
            "ZB015",
            "ZB016",
            "ZB017",
            "ZB011",
            "ZB012",
        ]

        plan = {
            "institutions": {
                "targets": [
                    {
                        "institution_id": "ORG007",
                        "role": "target",
                    }
                ]
            },
            "metrics": {
                "requested_metric_ids": metric_ids,
                "source_metric_ids": [],
                "concept_ids": [
                    "BC001",
                    "BC002",
                    "BC003",
                ],
            },
            "time": {
                "dates": ["2025-11-30"],
            },
        }

        context: dict[str, ExecutionValue] = {}

        for index, metric_id in enumerate(
            metric_ids,
            start=1,
        ):
            metric_key = metric_id.lower()
            record = {
                "institution_id": "ORG007",
                "institution_name": (
                    "江苏省G市农商行"
                ),
                "date": "2025-11-30",
                "metric_id": metric_id,
                "metric_name": f"指标{metric_id}",
                "unit": (
                    "%"
                    if metric_id != "ZB001"
                    else "亿元"
                ),
                "value": Decimal(str(index * 10)),
                "rank": index,
            }

            rank_ref = (
                "zb022_numeric_rank"
                if metric_id == "ZB022"
                else (
                    f"{metric_key}_performance_rank"
                )
            )
            context[rank_ref] = ExecutionValue(
                kind="records",
                data=[record],
            )

            if metric_id == "ZB022":
                continue

            top_records = (
                [record]
                if metric_id == "ZB001"
                else []
            )
            bottom_records = (
                [record]
                if metric_id == "ZB002"
                else []
            )

            context[
                f"{metric_key}_top3"
            ] = ExecutionValue(
                kind="records",
                data=top_records,
            )
            context[
                f"{metric_key}_bottom4"
            ] = ExecutionValue(
                kind="records",
                data=bottom_records,
            )

        facts = (
            DeterministicQueryPlanExecutor
            ._main_metrics_overview_facts(
                plan,
                context,
            )
        )

        self.assertIsInstance(
            facts,
            MainMetricsOverviewFacts,
        )
        assert facts is not None

        self.assertEqual(
            facts.subject.institution_id,
            "ORG007",
        )
        self.assertEqual(
            facts.subject.institution_name,
            "江苏省G市农商行",
        )
        self.assertEqual(
            facts.period,
            "2025-11-30",
        )
        self.assertEqual(len(facts.metrics), 9)

        bands = {
            item.metric_id: item.performance_band
            for item in facts.metrics
        }

        self.assertEqual(
            bands["ZB001"],
            "better",
        )
        self.assertEqual(
            bands["ZB002"],
            "worse",
        )
        self.assertEqual(
            bands["ZB022"],
            "numeric_only",
        )
        self.assertEqual(
            bands["ZB013"],
            "middle",
        )

        zb022 = next(
            item
            for item in facts.metrics
            if item.metric_id == "ZB022"
        )
        self.assertIsNone(
            zb022.performance_direction
        )


if __name__ == "__main__":
    unittest.main()
