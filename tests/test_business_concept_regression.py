import json
import unittest
from pathlib import Path

from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
    ExecutionValue,
)
from app.application.query_plan_validation import validate_business_rules


class BusinessConceptRegressionTest(unittest.TestCase):
    def test_mixed_scope_completeness_checks_target_and_province(self):
        executor = DeterministicQueryPlanExecutor(None)
        plan = {
            "institutions": {
                "targets": [
                    {
                        "institution_id": "ORG002",
                        "role": "target",
                    }
                ],
                "comparison_population": {
                    "type": "explicit",
                    "institution_ids": ["ORG001", "ORG002"],
                },
            }
        }
        records = [
            {"institution_id": "ORG001", "date": "2026-04-30", "metric_id": "ZB001"},
            {"institution_id": "ORG002", "date": "2026-04-30", "metric_id": "ZB001"},
            {"institution_id": "ORG001", "date": "2026-04-30", "metric_id": "ZB002"},
            {"institution_id": "ORG002", "date": "2026-04-30", "metric_id": "ZB002"},
            {"institution_id": "ORG002", "date": "2025-12-31", "metric_id": "ZB001"},
            {"institution_id": "ORG002", "date": "2025-12-31", "metric_id": "ZB002"},
            {"institution_id": "ORG002", "date": "2026-04-30", "metric_id": "ZB009"},
        ]

        executor._check_institution_completeness(
            plan,
            records,
            {"metric_ids": ["ZB001", "ZB002"]},
        )
        executor._check_metric_completeness(
            plan,
            records,
            {"metric_ids": ["ZB001", "ZB002", "ZB009"]},
        )

    def test_empty_target_group_is_omitted_and_columns_are_unique(self):
        executor = DeterministicQueryPlanExecutor(None)
        empty = ExecutionValue(
            kind="records",
            data=[],
            metadata={"output_ref": "top_group"},
        )
        record = ExecutionValue(
            kind="records",
            data=[
                {
                    "institution_id": "ORG002",
                    "institution_name": "乙银行",
                    "date": "2026-04-30",
                    "metric_id": "ZB001",
                    "metric_name": "各项存款余额",
                    "value": 80,
                    "unit": "亿元",
                    "rank": 2,
                }
            ],
            metadata={"output_ref": "bottom_group"},
        )
        value = ExecutionValue(
            kind="composite",
            data={"items": [empty, record]},
        )
        columns, rows, summary = executor._render(
            value,
            {
                "result_fields": [],
                "rounding": {"digits": 2},
                "_target_institution_ids": ["ORG002"],
            },
        )

        self.assertTrue(rows)
        self.assertEqual(len(columns), len(set(columns)))
        self.assertNotIn("没有符合条件的记录", summary or "")

    def test_bottom_n_uses_rank_numbers_after_ties(self):
        executor = DeterministicQueryPlanExecutor(None)
        ranked = ExecutionValue(
            kind="records",
            data=[
                {
                    "institution_id": f"ORG{index:03d}",
                    "date": "2026-01-31",
                    "metric_id": "ZB016",
                    "value": 100 - index,
                    "unit": "%",
                    "rank": rank,
                }
                for index, rank in enumerate(
                    [1, 2, 3, 4, 5, 6, 7, 8, 8, 8, 11, 12, 13],
                    start=1,
                )
            ],
            unit="%",
        )

        result = executor._op_take_n(
            [ranked],
            {"direction": "bottom", "n": 4},
        )
        selected_ranks = [
            item["rank"] for item in result.data
        ]

        self.assertEqual(selected_ranks, [11, 12, 13])

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.context = json.loads(
            (
                root
                / "config"
                / "query_planner"
                / "query_planner_context.json"
            ).read_text(encoding="utf-8")
        )

    def _rank_plan(self, n):
        ids = [f"ORG{index:03d}" for index in range(1, 14)]
        operations = []
        step = 1
        for metric_id, name in (
            ("ZB001", "deposit"),
            ("ZB002", "loan"),
            ("ZB013", "npl"),
            ("ZB011", "profit"),
        ):
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP001",
                    "input_refs": [metric_id],
                    "output_ref": f"{name}_all",
                    "parameters": {
                        "institution_ids": ids,
                        "date": "2026-04-30",
                    },
                }
            )
            step += 1
        operations.append(
            {
                "step": step,
                "operator_id": "OP006",
                "input_refs": ["loan_all", "deposit_all"],
                "output_ref": "ldr_all",
                "parameters": {
                    "numerator": "loan_all",
                    "denominator": "deposit_all",
                    "multiplier": 100,
                    "result_unit": "%",
                },
            }
        )
        step += 1

        specs = (
            ("deposit_all", "deposit_rank", "OP011", {"order": "descending"}),
            ("loan_all", "loan_rank", "OP011", {"order": "descending"}),
            ("ldr_all", "ldr_rank", "OP011", {"order": "descending"}),
            ("npl_all", "npl_rank", "OP012", {
                "metric_id": "ZB013",
                "performance_direction": "lower_is_better",
            }),
            ("profit_all", "profit_rank", "OP012", {
                "metric_id": "ZB011",
                "performance_direction": "higher_is_better",
            }),
        )
        final_refs = []
        for source_ref, rank_ref, operator_id, parameters in specs:
            operations.append(
                {
                    "step": step,
                    "operator_id": operator_id,
                    "input_refs": [source_ref],
                    "output_ref": rank_ref,
                    "parameters": parameters,
                }
            )
            step += 1
            wrapped = f"{rank_ref}_wrapped"
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP013",
                    "input_refs": [rank_ref],
                    "output_ref": wrapped,
                    "parameters": {"direction": "top", "n": n},
                }
            )
            step += 1
            final_refs.append(wrapped)
        operations.append(
            {
                "step": step,
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
                "targets": [{"institution_id": "ORG012", "role": "target"}],
                "comparison_population": {
                    "type": "all_official_institutions",
                    "institution_ids": ids,
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB001", "ZB002", "ZB022", "ZB013", "ZB011",
                ],
                "source_metric_ids": [
                    "ZB001", "ZB002", "ZB013", "ZB011",
                ],
                "concept_ids": ["BC004", "BC005", "BC006"],
            },
            "time": {
                "mode": "point",
                "dates": ["2026-04-30"],
                "start_date": None,
                "end_date": None,
                "grain": "day",
                "comparison_periods": [],
            },
            "operations": operations,
            "checks": [
                {
                    "type": "metric_completeness",
                    "parameters": {
                        "metric_ids": ["ZB001", "ZB002", "ZB013", "ZB011"],
                    },
                }
            ],
            "output": {
                "answer_type": "composite",
                "result_fields": [],
                "unit": None,
                "rounding": {"mode": "final_only", "digits": 2},
                "tie_policy": "preserve_all",
            },
        }

    def _income_structure_plan(self):
        institution_ids = [
            f"ORG{index:03d}" for index in range(1, 14)
        ]
        operations = []
        step = 1
        current_refs = {}
        base_refs = {}
        for metric_id in ("ZB011", "ZB012", "ZB008", "ZB007", "ZB009"):
            current_ref = f"{metric_id.lower()}_current"
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP001",
                    "input_refs": [metric_id],
                    "output_ref": current_ref,
                    "parameters": {
                        "institution_ids": institution_ids,
                        "date": "2026-04-30",
                    },
                }
            )
            current_refs[metric_id] = current_ref
            step += 1
            if metric_id != "ZB009":
                base_ref = f"{metric_id.lower()}_base"
                operations.append(
                    {
                        "step": step,
                        "operator_id": "OP001",
                        "input_refs": [metric_id],
                        "output_ref": base_ref,
                        "parameters": {
                            "institution_id": "ORG002",
                            "date": "2025-12-31",
                        },
                    }
                )
                base_refs[metric_id] = base_ref
                step += 1

        final_refs = list(current_refs.values())
        for metric_id, direction in (
            ("ZB011", "higher_is_better"),
            ("ZB012", "lower_is_better"),
            ("ZB008", "higher_is_better"),
            ("ZB007", "higher_is_better"),
        ):
            rank_ref = f"{metric_id.lower()}_rank"
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP012",
                    "input_refs": [current_refs[metric_id]],
                    "output_ref": rank_ref,
                    "parameters": {
                        "metric_id": metric_id,
                        "performance_direction": direction,
                    },
                }
            )
            step += 1
            final_refs.append(rank_ref)

        for metric_id, operator_id in (
            ("ZB011", "OP003"),
            ("ZB012", "OP008"),
            ("ZB008", "OP003"),
            ("ZB007", "OP003"),
        ):
            change_ref = f"{metric_id.lower()}_change"
            operations.append(
                {
                    "step": step,
                    "operator_id": operator_id,
                    "input_refs": [
                        current_refs[metric_id],
                        base_refs[metric_id],
                    ],
                    "output_ref": change_ref,
                    "parameters": {},
                }
            )
            step += 1
            final_refs.append(change_ref)

        for numerator, output_ref in (
            ("ZB008", "net_interest_ratio_current"),
            ("ZB007", "intermediate_income_ratio_current"),
        ):
            operations.append(
                {
                    "step": step,
                    "operator_id": "OP006",
                    "input_refs": [
                        current_refs[numerator],
                        current_refs["ZB009"],
                    ],
                    "output_ref": output_ref,
                    "parameters": {
                        "multiplier": 100,
                        "result_unit": "%",
                    },
                }
            )
            step += 1
            final_refs.append(output_ref)

        operations.append(
            {
                "step": step,
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
                "targets": [{"institution_id": "ORG002", "role": "target"}],
                "comparison_population": {
                    "type": "all_official_institutions",
                    "institution_ids": institution_ids,
                },
            },
            "metrics": {
                "requested_metric_ids": [
                    "ZB011", "ZB012", "ZB008", "ZB007", "ZB034",
                ],
                "source_metric_ids": [
                    "ZB011", "ZB012", "ZB008", "ZB007", "ZB009",
                ],
                "concept_ids": ["BC006", "BC007"],
            },
            "time": {
                "mode": "comparison",
                "dates": ["2025-12-31", "2026-04-30"],
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

    def test_full_rank_wrapper_is_accepted(self):
        errors = validate_business_rules(
            self._rank_plan(13),
            self.context,
            "从规模、资产质量、盈利能力三个维度，"
            "分别列出江苏省L市农商行在2026-04-30的各项指标及排名。",
        )
        messages = "\n".join(item["message"] for item in errors)
        self.assertNotIn("排名未合并进最终结果", messages)

    def test_top_one_wrapper_is_rejected(self):
        errors = validate_business_rules(
            self._rank_plan(1),
            self.context,
            "从规模、资产质量、盈利能力三个维度，"
            "分别列出江苏省L市农商行在2026-04-30的各项指标及排名。",
        )
        messages = "\n".join(item["message"] for item in errors)
        self.assertIn("排名未合并进最终结果", messages)

    def test_income_structure_requires_both_current_ratios(self):
        for removed_ref, expected_message in (
            (
                "net_interest_ratio_current",
                "净利息收入占营业收入比重",
            ),
            (
                "intermediate_income_ratio_current",
                "中间业务收入占营业收入比重",
            ),
        ):
            with self.subTest(removed_ref=removed_ref):
                plan = self._income_structure_plan()
                plan["operations"] = [
                    operation
                    for operation in plan["operations"]
                    if operation["output_ref"] != removed_ref
                ]
                for index, operation in enumerate(
                    plan["operations"],
                    start=1,
                ):
                    operation["step"] = index
                    if operation["operator_id"] == "OP019":
                        operation["input_refs"].remove(removed_ref)

                errors = validate_business_rules(
                    plan,
                    self.context,
                    "分析盈利能力，包含净利润、成本收入比、收入结构和较年初变化。",
                )
                messages = "\n".join(
                    item["message"] for item in errors
                )
                self.assertIn(expected_message, messages)

    def test_income_structure_requires_income_amount_changes(self):
        for metric_id in ("ZB008", "ZB007"):
            with self.subTest(metric_id=metric_id):
                plan = self._income_structure_plan()
                removed_ref = f"{metric_id.lower()}_change"
                plan["operations"] = [
                    operation
                    for operation in plan["operations"]
                    if operation["output_ref"] != removed_ref
                ]
                for index, operation in enumerate(
                    plan["operations"],
                    start=1,
                ):
                    operation["step"] = index
                    if operation["operator_id"] == "OP019":
                        operation["input_refs"].remove(removed_ref)

                errors = validate_business_rules(
                    plan,
                    self.context,
                    "分析盈利能力，包含净利润、成本收入比、收入结构和较年初变化。",
                )
                messages = "\n".join(
                    item["message"] for item in errors
                )
                self.assertIn(
                    f"{metric_id}较年初变化必须使用OP003",
                    messages,
                )


if __name__ == "__main__":
    unittest.main()
