import copy
import json
import unittest
from pathlib import Path

from app.adapters.planning.llm_query_planner import LLMQueryPlanner
from app.application.query_plan_normalization import normalize_query_plan


PERFORMANCE_DIRECTIONS = {
    "ZB001": "higher_is_better",
    "ZB002": "higher_is_better",
    "ZB013": "lower_is_better",
    "ZB015": "higher_is_better",
    "ZB016": "higher_is_better",
    "ZB017": "lower_is_better",
    "ZB011": "higher_is_better",
    "ZB012": "lower_is_better",
}


class BusinessConceptPlanNormalizationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        planner_root = root / "config" / "query_planner"
        cls.schema = json.loads(
            (planner_root / "query_plan.schema.json").read_text(encoding="utf-8")
        )
        cls.context = json.loads(
            (planner_root / "query_planner_context.json").read_text(
                encoding="utf-8"
            )
        )

    def _plan(self):
        metric_ids = list(PERFORMANCE_DIRECTIONS)
        operations = []
        for metric_id in metric_ids:
            operations.append(
                {
                    "step": len(operations) + 1,
                    "operator_id": "OP001",
                    "input_refs": [metric_id],
                    "output_ref": f"{metric_id.lower()}_values",
                    "parameters": {
                        "institution_ids": [
                            f"ORG{index:03d}" for index in range(1, 14)
                        ],
                        "date": "2025-11-30",
                    },
                }
            )
        operations.append(
            {
                "step": len(operations) + 1,
                "operator_id": "OP006",
                "input_refs": ["zb002_values", "zb001_values"],
                "output_ref": "zb022_values",
                "parameters": {
                    "numerator": "zb002_values",
                    "denominator": "zb001_values",
                    "multiplier": 100,
                    "result_unit": "%",
                },
            }
        )

        # Simulate an LLM plan that creates classification ranks for only
        # some metrics and exposes only the Top/Bottom slices.
        final_refs = [f"{metric_id.lower()}_values" for metric_id in metric_ids]
        final_refs.append("zb022_values")
        for metric_id in ("ZB001", "ZB013"):
            rank_ref = f"{metric_id.lower()}_performance_rank"
            operations.append(
                {
                    "step": len(operations) + 1,
                    "operator_id": "OP012",
                    "input_refs": [f"{metric_id.lower()}_values"],
                    "output_ref": rank_ref,
                    "parameters": {
                        "metric_id": metric_id,
                        "performance_direction": PERFORMANCE_DIRECTIONS[metric_id],
                    },
                }
            )
            for direction, n in (("top", 3), ("bottom", 4)):
                output_ref = f"{metric_id.lower()}_{direction}"
                operations.append(
                    {
                        "step": len(operations) + 1,
                        "operator_id": "OP013",
                        "input_refs": [rank_ref],
                        "output_ref": output_ref,
                        "parameters": {"direction": direction, "n": n},
                    }
                )
                final_refs.append(output_ref)

        operations.append(
            {
                "step": len(operations) + 1,
                "operator_id": "OP019",
                "input_refs": final_refs,
                "output_ref": "final_result",
                "parameters": {},
            }
        )
        return {
            "status": {
                "code": "executable",
                "reason": None,
                "clarification_question": None,
            },
            "institutions": {
                "targets": [{"institution_id": "ORG007", "role": "target"}],
                "comparison_population": {
                    "type": "all_official_institutions",
                    "institution_ids": [
                        f"ORG{index:03d}" for index in range(1, 14)
                    ],
                },
            },
            "metrics": {
                "requested_metric_ids": metric_ids + ["ZB022"],
                "source_metric_ids": metric_ids,
                "concept_ids": ["BC001", "BC002", "BC003"],
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
            "checks": [],
            "output": {
                "answer_type": "composite",
                "result_fields": [],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": "preserve_all",
            },
        }

    @staticmethod
    def _full_rank_operations(plan):
        return [
            operation
            for operation in plan["operations"]
            if operation["operator_id"] in {"OP011", "OP012"}
        ]

    def test_completes_all_nine_full_rankings(self):
        normalized = normalize_query_plan(self._plan())
        rankings = self._full_rank_operations(normalized)
        self.assertEqual(len(rankings), 9)
        final_refs = normalized["operations"][-1]["input_refs"]
        self.assertTrue(
            all(operation["output_ref"] in final_refs for operation in rankings)
        )

    def test_existing_rankings_are_reused_not_duplicated(self):
        normalized = normalize_query_plan(self._plan())
        zb001 = [
            operation
            for operation in self._full_rank_operations(normalized)
            if operation.get("parameters", {}).get("metric_id") == "ZB001"
        ]
        self.assertEqual(len(zb001), 1)
        self.assertIn(
            "zb001_performance_rank",
            normalized["operations"][-1]["input_refs"],
        )

    def test_top_and_bottom_slices_do_not_replace_full_ranking(self):
        normalized = normalize_query_plan(self._plan())
        final_refs = normalized["operations"][-1]["input_refs"]
        self.assertIn("zb001_performance_rank", final_refs)
        self.assertIn("zb001_top", final_refs)
        self.assertIn("zb001_bottom", final_refs)

    def test_zb022_uses_numeric_ranking_only(self):
        normalized = normalize_query_plan(self._plan())
        zb022 = [
            operation
            for operation in self._full_rank_operations(normalized)
            if operation["output_ref"].startswith("bc001_zb022")
        ]
        self.assertEqual(len(zb022), 1)
        self.assertEqual(zb022[0]["operator_id"], "OP011")
        self.assertEqual(zb022[0]["parameters"], {"order": "descending"})

    def test_performance_directions_are_frozen(self):
        normalized = normalize_query_plan(self._plan())
        actual = {
            operation["parameters"]["metric_id"]: operation["parameters"][
                "performance_direction"
            ]
            for operation in self._full_rank_operations(normalized)
            if operation["operator_id"] == "OP012"
        }
        self.assertEqual(actual, PERFORMANCE_DIRECTIONS)

    def test_numeric_rank_does_not_replace_frozen_performance_rank(self):
        plan = self._plan()
        final = plan["operations"].pop()
        plan["operations"].append(
            {
                "step": len(plan["operations"]) + 1,
                "operator_id": "OP011",
                "input_refs": ["zb012_values"],
                "output_ref": "zb012_numeric_rank",
                "parameters": {"order": "descending"},
            }
        )
        plan["operations"].append(final)
        normalized = normalize_query_plan(plan)
        zb012 = [
            operation
            for operation in self._full_rank_operations(normalized)
            if operation.get("parameters", {}).get("metric_id") == "ZB012"
        ]
        self.assertEqual(len(zb012), 1)
        self.assertEqual(
            zb012[0]["parameters"]["performance_direction"],
            "lower_is_better",
        )
        self.assertIn(
            zb012[0]["output_ref"],
            normalized["operations"][-1]["input_refs"],
        )

    def test_normalization_is_idempotent(self):
        once = normalize_query_plan(self._plan())
        twice = normalize_query_plan(once)
        self.assertEqual(twice, once)
        self.assertEqual(
            [operation["step"] for operation in twice["operations"]],
            list(range(1, len(twice["operations"]) + 1)),
        )

    def test_other_concept_combinations_are_unchanged(self):
        plan = self._plan()
        plan["metrics"]["concept_ids"] = ["BC001", "BC002"]
        original = copy.deepcopy(plan)
        self.assertEqual(normalize_query_plan(plan), original)

    def test_planner_validates_the_normalized_plan(self):
        planner = LLMQueryPlanner(
            provider=None,
            prompt="prompt",
            schema=self.schema,
            context=self.context,
            timeout_seconds=20,
        )
        validation = planner._validate(
            self._plan(),
            "请列出主要经营指标及排名，哪些表现较好，哪些表现较差？",
        )
        rankings = self._full_rank_operations(validation.query_plan)
        self.assertFalse(
            any(
                error["path"].startswith("operations")
                for error in validation.schema_errors
            ),
            validation.schema_errors,
        )
        self.assertEqual(len(rankings), 9)
        final_refs = validation.query_plan["operations"][-1]["input_refs"]
        self.assertTrue(
            all(operation["output_ref"] in final_refs for operation in rankings)
        )


if __name__ == "__main__":
    unittest.main()
