from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.application.business_concept_fast_matcher import (
    MainMetricsQueryMatch,
)


MAIN_METRIC_IDS = [
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

SOURCE_METRIC_IDS = [
    "ZB001",
    "ZB002",
    "ZB013",
    "ZB015",
    "ZB016",
    "ZB017",
    "ZB011",
    "ZB012",
]

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


def _official_institution_ids(
    context: Mapping[str, Any],
) -> list[str]:
    institutions = context.get("institutions")

    if not isinstance(institutions, list):
        raise ValueError("正式语义上下文缺少 institutions。")

    institution_ids: list[str] = []

    for institution in institutions:
        if not isinstance(institution, Mapping):
            continue

        institution_id = institution.get("institution_id")

        if isinstance(institution_id, str):
            institution_ids.append(institution_id)

    if not institution_ids:
        raise ValueError("正式语义上下文中没有合法机构。")

    return institution_ids


def build_main_metrics_plan(
    match: MainMetricsQueryMatch,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    institution_ids = _official_institution_ids(context)
    operations: list[dict[str, Any]] = []

    def add_operation(
        operator_id: str,
        input_refs: list[str],
        output_ref: str,
        parameters: dict[str, Any],
    ) -> None:
        operations.append(
            {
                "step": len(operations) + 1,
                "operator_id": operator_id,
                "input_refs": input_refs,
                "output_ref": output_ref,
                "parameters": parameters,
            }
        )

    raw_value_refs: list[str] = []

    for metric_id in SOURCE_METRIC_IDS:
        output_ref = f"{metric_id.lower()}_values"
        raw_value_refs.append(output_ref)

        add_operation(
            operator_id="OP001",
            input_refs=[metric_id],
            output_ref=output_ref,
            parameters={
                "institution_ids": institution_ids,
                "date": match.data_date,
            },
        )

    add_operation(
        operator_id="OP006",
        input_refs=["zb002_values", "zb001_values"],
        output_ref="zb022_values",
        parameters={
            "numerator": "zb002_values",
            "denominator": "zb001_values",
            "multiplier": 100,
            "result_unit": "%",
        },
    )

    full_rank_refs: list[str] = []
    classification_refs: list[str] = []

    for metric_id, direction in PERFORMANCE_DIRECTIONS.items():
        value_ref = f"{metric_id.lower()}_values"
        rank_ref = f"{metric_id.lower()}_performance_rank"

        add_operation(
            operator_id="OP012",
            input_refs=[value_ref],
            output_ref=rank_ref,
            parameters={
                "metric_id": metric_id,
                "performance_direction": direction,
            },
        )

        full_rank_refs.append(rank_ref)

        top_ref = f"{metric_id.lower()}_top3"
        add_operation(
            operator_id="OP013",
            input_refs=[rank_ref],
            output_ref=top_ref,
            parameters={
                "direction": "top",
                "n": 3,
            },
        )
        classification_refs.append(top_ref)

        bottom_ref = f"{metric_id.lower()}_bottom4"
        add_operation(
            operator_id="OP013",
            input_refs=[rank_ref],
            output_ref=bottom_ref,
            parameters={
                "direction": "bottom",
                "n": 4,
            },
        )
        classification_refs.append(bottom_ref)

    add_operation(
        operator_id="OP011",
        input_refs=["zb022_values"],
        output_ref="zb022_numeric_rank",
        parameters={
            "order": "descending",
        },
    )
    full_rank_refs.append("zb022_numeric_rank")

    final_refs = [
        *raw_value_refs,
        "zb022_values",
        *full_rank_refs,
        *classification_refs,
    ]

    add_operation(
        operator_id="OP019",
        input_refs=final_refs,
        output_ref="final_result",
        parameters={},
    )

    return {
        "status": {
            "code": "executable",
            "reason": None,
            "clarification_question": None,
        },
        "institutions": {
            "targets": [
                {
                    "institution_id": match.institution_id,
                    "role": "target",
                }
            ],
            "comparison_population": {
                "type": "all_official_institutions",
                "institution_ids": institution_ids,
            },
        },
        "metrics": {
            "requested_metric_ids": MAIN_METRIC_IDS,
            "source_metric_ids": SOURCE_METRIC_IDS,
            "concept_ids": ["BC001", "BC002", "BC003"],
        },
        "time": {
            "mode": "point",
            "dates": [match.data_date],
            "start_date": None,
            "end_date": None,
            "grain": "day",
            "comparison_periods": [],
        },
        "operations": operations,
        "checks": [
            {
                "type": "record_exists",
                "parameters": {
                    "metric_ids": list(SOURCE_METRIC_IDS),
                    "date": match.data_date,
                },
            },
            {
                "type": "institution_completeness",
                "parameters": {
                    "metric_ids": list(SOURCE_METRIC_IDS),
                    "institution_ids": list(institution_ids),
                    "date": match.data_date,
                },
            },
            {
                "type": "metric_completeness",
                "parameters": {
                    "metric_ids": list(SOURCE_METRIC_IDS),
                    "institution_ids": list(institution_ids),
                    "date": match.data_date,
                },
            },
            {
                "type": "denominator_nonzero",
                "parameters": {
                    "metric_ids": ["ZB001"],
                },
            },
            {
                "type": "unrounded_comparison",
                "parameters": {
                    "metric_ids": list(MAIN_METRIC_IDS),
                },
            },
            {
                "type": "tie_preservation",
                "parameters": {
                    "metric_ids": list(MAIN_METRIC_IDS),
                },
            },
        ],
        "output": {
            "answer_type": "composite",
            "result_fields": [],
            "unit": None,
            "rounding": {
                "mode": "final_only",
                "digits": 2,
            },
            "tie_policy": "preserve_all",
        },
    }
