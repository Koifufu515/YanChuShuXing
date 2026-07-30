from __future__ import annotations

from copy import deepcopy
from typing import Any


_MAIN_METRIC_DIRECTIONS = {
    "ZB001": "higher_is_better",
    "ZB002": "higher_is_better",
    "ZB013": "lower_is_better",
    "ZB015": "higher_is_better",
    "ZB016": "higher_is_better",
    "ZB017": "lower_is_better",
    "ZB011": "higher_is_better",
    "ZB012": "lower_is_better",
}
_MAIN_METRICS = (*_MAIN_METRIC_DIRECTIONS, "ZB022")


def normalize_query_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Apply deterministic, idempotent repairs for frozen business concepts."""
    normalized = deepcopy(plan)
    _complete_metric_completeness_check(normalized)
    if not _requires_main_metric_ranking_completion(normalized):
        return normalized

    operations = normalized.get("operations")
    if not isinstance(operations, list) or not operations:
        return normalized
    if not all(isinstance(operation, dict) for operation in operations):
        return normalized

    final_merge = operations[-1]
    if final_merge.get("operator_id") != "OP019":
        return normalized
    final_refs = final_merge.get("input_refs")
    if not isinstance(final_refs, list):
        return normalized

    output_to_operation = {
        operation.get("output_ref"): operation
        for operation in operations
        if isinstance(operation.get("output_ref"), str)
    }
    source_cache: dict[str, frozenset[str]] = {}

    def source_metrics(
        ref: str,
        visiting: frozenset[str] = frozenset(),
    ) -> frozenset[str]:
        if ref.startswith("ZB") and len(ref) == 5:
            return frozenset({ref})
        if ref in source_cache:
            return source_cache[ref]
        if ref in visiting:
            return frozenset()
        operation = output_to_operation.get(ref)
        if not isinstance(operation, dict):
            return frozenset()
        result: set[str] = set()
        for input_ref in operation.get("input_refs", []):
            if isinstance(input_ref, str):
                result.update(source_metrics(input_ref, visiting | {ref}))
        frozen = frozenset(result)
        source_cache[ref] = frozen
        return frozen

    performance_rankings: dict[str, str] = {}
    numeric_rankings: dict[str, str] = {}
    sources: dict[str, str] = {}
    for operation in operations[:-1]:
        operator_id = operation.get("operator_id")
        output_ref = operation.get("output_ref")
        if not isinstance(output_ref, str):
            continue

        if operator_id == "OP012":
            parameters = operation.get("parameters")
            metric_id = (
                parameters.get("metric_id")
                if isinstance(parameters, dict)
                else None
            )
            if (
                metric_id in _MAIN_METRIC_DIRECTIONS
                and isinstance(parameters, dict)
                and parameters.get("performance_direction")
                == _MAIN_METRIC_DIRECTIONS[metric_id]
            ):
                performance_rankings.setdefault(metric_id, output_ref)
            continue

        resolved = source_metrics(output_ref)
        inferred_metric = _metric_for_sources(resolved)
        if operator_id == "OP011" and inferred_metric in _MAIN_METRICS:
            numeric_rankings.setdefault(inferred_metric, output_ref)
        elif (
            operator_id not in {"OP011", "OP012", "OP013", "OP019"}
            and inferred_metric in _MAIN_METRICS
        ):
            sources.setdefault(inferred_metric, output_ref)

    additions: list[dict[str, Any]] = []
    existing_outputs = set(output_to_operation)
    for metric_id in _MAIN_METRICS:
        rank_ref = (
            numeric_rankings.get(metric_id)
            if metric_id == "ZB022"
            else performance_rankings.get(metric_id)
        )
        if rank_ref is None:
            source_ref = sources.get(metric_id)
            if source_ref is None:
                continue
            rank_ref = _unique_output_ref(
                f"bc001_{metric_id.lower()}_full_rank",
                existing_outputs,
            )
            if metric_id == "ZB022":
                operator_id = "OP011"
                parameters = {"order": "descending"}
            else:
                operator_id = "OP012"
                parameters = {
                    "metric_id": metric_id,
                    "performance_direction": _MAIN_METRIC_DIRECTIONS[metric_id],
                }
            additions.append(
                {
                    "step": 0,
                    "operator_id": operator_id,
                    "input_refs": [source_ref],
                    "output_ref": rank_ref,
                    "parameters": parameters,
                }
            )
            existing_outputs.add(rank_ref)
        if rank_ref not in final_refs:
            final_refs.append(rank_ref)

    operations[-1:-1] = additions
    for step, operation in enumerate(operations, start=1):
        operation["step"] = step
    return normalized


def _complete_metric_completeness_check(
    plan: dict[str, Any],
) -> None:
    status = plan.get("status")
    if not isinstance(status, dict) or status.get("code") != "executable":
        return

    metrics = plan.get("metrics")
    source_metric_ids = (
        metrics.get("source_metric_ids")
        if isinstance(metrics, dict)
        else None
    )
    if (
        not isinstance(source_metric_ids, list)
        or len(source_metric_ids) < 2
        or len(set(source_metric_ids)) != len(source_metric_ids)
        or not all(
            isinstance(metric_id, str)
            and len(metric_id) == 5
            and metric_id.startswith("ZB")
            and metric_id[2:].isdigit()
            for metric_id in source_metric_ids
        )
    ):
        return

    checks = plan.get("checks")
    if not isinstance(checks, list):
        return
    if any(
        isinstance(check, dict)
        and check.get("type") == "metric_completeness"
        for check in checks
    ):
        return

    checks.append(
        {
            "type": "metric_completeness",
            "parameters": {
                "metric_ids": list(source_metric_ids),
            },
        }
    )


def _requires_main_metric_ranking_completion(plan: dict[str, Any]) -> bool:
    status = plan.get("status")
    if not isinstance(status, dict) or status.get("code") != "executable":
        return False
    metrics = plan.get("metrics")
    concept_ids = metrics.get("concept_ids") if isinstance(metrics, dict) else None
    return isinstance(concept_ids, list) and {
        "BC001",
        "BC002",
        "BC003",
    }.issubset(set(concept_ids))


def _metric_for_sources(source_metrics: frozenset[str]) -> str | None:
    if len(source_metrics) == 1:
        metric_id = next(iter(source_metrics))
        return metric_id if metric_id in _MAIN_METRIC_DIRECTIONS else None
    if source_metrics == frozenset({"ZB001", "ZB002"}):
        return "ZB022"
    return None


def _unique_output_ref(candidate: str, existing: set[str]) -> str:
    if candidate not in existing:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in existing:
        suffix += 1
    return f"{candidate}_{suffix}"
