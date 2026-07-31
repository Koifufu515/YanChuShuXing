from __future__ import annotations

import calendar
import json
import operator
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import perf_counter
from typing import Any, Callable, Iterable

from app.application.errors import QueryExecutionError
from app.application.answer_models import (
    BenchmarkComparisonFacts,
    InstitutionRef,
    MainMetricFact,
    MainMetricsOverviewFacts,
    MetricRef,
    TrendOverviewFacts,
    TrendPoint,
    TrendSeries,
    MetricRankingFacts,
    RankingItem,
    RankingOverviewFacts,
    ExtremeMetricItem,
    ExtremeMetricFacts,
    DirectMetricValueFact,
    DirectMetricValuesFacts,
    CalculationInputFact,
    CalculatedMetricFacts,
    ReconciliationComponentFact,
    ReconciliationFacts,
)
from app.application.models import JsonScalar, QueryPlanExecutionResult
from app.ports.database_executor import DatabaseExecutor


_PERIOD_AVERAGE_FACT_METRICS = {
    "ZB031": {
        "source_metric_id": "ZB001",
        "metric_name": "日均存款余额",
    },
    "ZB032": {
        "source_metric_id": "ZB002",
        "metric_name": "日均贷款余额",
    },
    "ZB033": {
        "source_metric_id": "ZB011",
        "metric_name": "日均净利润",
    },
}


@dataclass
class ExecutionValue:
    kind: str
    data: Any
    unit: str | None = None
    operator_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DeterministicQueryPlanExecutor:
    """使用固定 SQL 模板和确定性 Python 算子执行标准查询计划。"""

    def __init__(self, database_executor: DatabaseExecutor) -> None:
        self.database_executor = database_executor

    def execute(self, query_plan: dict[str, Any]) -> QueryPlanExecutionResult:
        status = query_plan.get("status")
        if not isinstance(status, dict) or status.get("code") != "executable":
            raise QueryExecutionError("只有 executable 查询计划可以进入执行器。")

        operations = query_plan.get("operations")
        if not isinstance(operations, list) or not operations:
            raise QueryExecutionError("可执行查询计划缺少 operations。")

        context: dict[str, ExecutionValue] = {}
        trace: list[dict[str, Any]] = []
        expected_step = 1

        for operation_plan in operations:
            if not isinstance(operation_plan, dict):
                raise QueryExecutionError("查询计划包含非法操作节点。")
            step = operation_plan.get("step")
            if step != expected_step:
                raise QueryExecutionError("operations.step 必须从1开始连续递增。")
            expected_step += 1

            operator_id = operation_plan.get("operator_id")
            output_ref = operation_plan.get("output_ref")
            input_refs = operation_plan.get("input_refs")
            parameters = operation_plan.get("parameters")
            if not isinstance(operator_id, str) or not isinstance(output_ref, str):
                raise QueryExecutionError("操作节点缺少 operator_id 或 output_ref。")
            if output_ref in context:
                raise QueryExecutionError(f"output_ref 重复：{output_ref}")
            if not isinstance(input_refs, list) or not isinstance(parameters, dict):
                raise QueryExecutionError("操作节点 input_refs 或 parameters 格式错误。")

            started = perf_counter()
            result = self._dispatch(
                operator_id=operator_id,
                input_refs=input_refs,
                parameters=parameters,
                context=context,
            )
            result.operator_id = operator_id
            result.metadata.setdefault("output_ref", output_ref)
            context[output_ref] = result
            trace.append(
                {
                    "step": step,
                    "operator_id": operator_id,
                    "input_refs": list(input_refs),
                    "output_ref": output_ref,
                    "result_kind": result.kind,
                    "record_count": self._record_count(result),
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                }
            )

        self._run_checks(query_plan, context)
        final_ref = operations[-1]["output_ref"]
        final_value = context[final_ref]
        output_plan = dict(
            query_plan.get("output")
            if isinstance(query_plan.get("output"), dict)
            else {}
        )
        institutions = query_plan.get("institutions")
        targets = (
            institutions.get("targets")
            if isinstance(institutions, dict)
            else []
        )
        targets = targets if isinstance(targets, list) else []
        output_plan["_target_institution_ids"] = [
            item.get("institution_id")
            for item in targets
            if isinstance(item, dict)
            and isinstance(item.get("institution_id"), str)
        ]
        columns, rows, summary = self._render(
            final_value,
            output_plan,
        )
        analysis_facts = self._trend_overview_facts(
            query_plan,
            final_value,
        )
        if analysis_facts is None:
            analysis_facts = self._main_metrics_overview_facts(
                query_plan,
                context,
            )
        if analysis_facts is None:
            analysis_facts = self._ranking_overview_facts(
                query_plan,
                context,
            )
        if analysis_facts is None:
            analysis_facts = self._extreme_metric_facts(
                query_plan,
                context,
            )
        if analysis_facts is None:
            analysis_facts = self._direct_metric_values_facts(
                query_plan,
                context,
            )
        if analysis_facts is None:
            analysis_facts = self._benchmark_comparison_facts(
                query_plan,
                final_value,
            )
        if analysis_facts is None:
            analysis_facts = self._reconciliation_facts(
                query_plan,
                context,
            )
        if analysis_facts is None:
            analysis_facts = self._calculated_metric_facts(
                query_plan,
                context,
            )
        return QueryPlanExecutionResult(
            columns=columns,
            rows=rows,
            summary=summary,
            warnings=[],
            execution_trace=trace,
            analysis_facts=analysis_facts,
        )

    @staticmethod
    def _trend_overview_facts(
        query_plan: dict[str, Any],
        final_value: ExecutionValue,
    ) -> TrendOverviewFacts | None:
        if (
            final_value.kind != "trend"
            or not isinstance(final_value.data, dict)
        ):
            return None

        raw_records = final_value.data.get("series")
        if not isinstance(raw_records, list):
            return None

        records = [
            item
            for item in raw_records
            if isinstance(item, dict)
        ]
        if not records:
            return None

        time_plan = query_plan.get("time")
        time_plan = (
            time_plan
            if isinstance(time_plan, dict)
            else {}
        )

        grain = time_plan.get("grain")
        grain = (
            grain
            if isinstance(grain, str)
            and grain
            else "day"
        )

        performance_directions = {
            "ZB001": "higher_is_better",
            "ZB002": "higher_is_better",
            "ZB011": "higher_is_better",
            "ZB012": "lower_is_better",
            "ZB013": "lower_is_better",
            "ZB015": "higher_is_better",
            "ZB016": "higher_is_better",
            "ZB017": "lower_is_better",
        }

        grouped: dict[
            tuple[str | None, str],
            list[dict[str, Any]],
        ] = defaultdict(list)

        all_dates: list[str] = []

        for record in records:
            institution_id = record.get(
                "institution_id"
            )
            institution_name = record.get(
                "institution_name"
            )
            metric_id = record.get("metric_id")
            metric_name = record.get("metric_name")
            unit = record.get("unit")
            data_date = record.get("date")
            value = record.get("value")

            if (
                institution_id is not None
                and not isinstance(
                    institution_id,
                    str,
                )
            ):
                return None

            if not all(
                isinstance(item, str)
                and item
                for item in (
                    institution_name,
                    metric_id,
                    metric_name,
                    unit,
                    data_date,
                )
            ):
                return None

            if value is None:
                return None

            try:
                date.fromisoformat(data_date)
            except ValueError:
                return None

            grouped[
                (institution_id, metric_id)
            ].append(record)
            all_dates.append(data_date)

        if not grouped or not all_dates:
            return None

        start_date = time_plan.get("start_date")
        if not isinstance(start_date, str):
            start_date = min(all_dates)

        end_date = time_plan.get("end_date")
        if not isinstance(end_date, str):
            end_date = max(all_dates)

        try:
            parsed_start = date.fromisoformat(
                start_date
            )
            parsed_end = date.fromisoformat(
                end_date
            )
        except ValueError:
            return None

        if parsed_start > parsed_end:
            return None

        trend_series: list[TrendSeries] = []

        for (
            institution_id,
            metric_id,
        ), group in sorted(
            grouped.items(),
            key=lambda item: (
                str(item[0][0] or ""),
                item[0][1],
            ),
        ):
            institution_names = {
                str(item["institution_name"])
                for item in group
            }
            metric_names = {
                str(item["metric_name"])
                for item in group
            }
            units = {
                str(item["unit"])
                for item in group
            }

            if (
                len(institution_names) != 1
                or len(metric_names) != 1
                or len(units) != 1
            ):
                return None

            ordered = sorted(
                group,
                key=lambda item: str(
                    item["date"]
                ),
            )

            point_dates = [
                str(item["date"])
                for item in ordered
            ]
            if len(point_dates) != len(
                set(point_dates)
            ):
                return None

            points = [
                TrendPoint(
                    data_date=str(item["date"]),
                    value=(
                        DeterministicQueryPlanExecutor
                        ._json_scalar(item["value"])
                    ),
                )
                for item in ordered
            ]

            trend_series.append(
                TrendSeries(
                    institution=InstitutionRef(
                        institution_id=(
                            institution_id
                        ),
                        institution_name=next(
                            iter(
                                institution_names
                            )
                        ),
                    ),
                    metric=MetricRef(
                        metric_id=metric_id,
                        metric_name=next(
                            iter(metric_names)
                        ),
                        unit=next(iter(units)),
                        performance_direction=(
                            performance_directions.get(
                                metric_id,
                                "not_applicable",
                            )
                        ),
                    ),
                    points=points,
                )
            )

        return TrendOverviewFacts(
            start_date=start_date,
            end_date=end_date,
            grain=grain,
            series=trend_series,
        )

    @staticmethod
    def _main_metrics_overview_facts(
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> MainMetricsOverviewFacts | None:
        metrics_plan = query_plan.get("metrics")
        if not isinstance(metrics_plan, dict):
            return None

        concept_ids = metrics_plan.get("concept_ids")
        if not isinstance(concept_ids, list):
            return None

        required_concepts = {
            "BC001",
            "BC002",
            "BC003",
        }
        if not required_concepts.issubset(
            {
                value
                for value in concept_ids
                if isinstance(value, str)
            }
        ):
            return None

        expected_metric_ids = [
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
        if (
            metrics_plan.get("requested_metric_ids")
            != expected_metric_ids
        ):
            return None

        institutions = query_plan.get("institutions")
        targets = (
            institutions.get("targets")
            if isinstance(institutions, dict)
            else None
        )
        if not isinstance(targets, list) or len(targets) != 1:
            return None

        target = targets[0]
        target_id = (
            target.get("institution_id")
            if isinstance(target, dict)
            else None
        )
        if not isinstance(target_id, str):
            return None

        time_plan = query_plan.get("time")
        dates = (
            time_plan.get("dates")
            if isinstance(time_plan, dict)
            else None
        )
        if (
            not isinstance(dates, list)
            or len(dates) != 1
            or not isinstance(dates[0], str)
        ):
            return None
        period = dates[0]

        performance_directions = {
            "ZB001": "higher_is_better",
            "ZB002": "higher_is_better",
            "ZB013": "lower_is_better",
            "ZB015": "higher_is_better",
            "ZB016": "higher_is_better",
            "ZB017": "lower_is_better",
            "ZB011": "higher_is_better",
            "ZB012": "lower_is_better",
        }

        def records_for(
            output_ref: str,
        ) -> list[dict[str, Any]] | None:
            value = context.get(output_ref)
            if (
                not isinstance(value, ExecutionValue)
                or value.kind != "records"
                or not isinstance(value.data, list)
            ):
                return None
            return [
                item
                for item in value.data
                if isinstance(item, dict)
            ]

        metric_facts: list[MainMetricFact] = []
        institution_name: str | None = None

        for metric_id in expected_metric_ids:
            metric_key = metric_id.lower()
            rank_ref = (
                "zb022_numeric_rank"
                if metric_id == "ZB022"
                else f"{metric_key}_performance_rank"
            )
            ranked_records = records_for(rank_ref)
            if ranked_records is None:
                return None

            target_records = [
                item
                for item in ranked_records
                if item.get("institution_id") == target_id
            ]
            if len(target_records) != 1:
                return None

            record = target_records[0]
            required_values = (
                record.get("institution_name"),
                record.get("metric_name"),
                record.get("unit"),
                record.get("value"),
                record.get("rank"),
                record.get("date"),
            )
            if any(value is None for value in required_values):
                return None

            if record.get("date") != period:
                return None

            rank = record.get("rank")
            if (
                isinstance(rank, bool)
                or not isinstance(rank, int)
            ):
                return None

            current_name = record.get("institution_name")
            if not isinstance(current_name, str):
                return None
            if institution_name is None:
                institution_name = current_name
            elif institution_name != current_name:
                return None

            performance_direction = (
                performance_directions.get(metric_id)
            )

            if metric_id == "ZB022":
                performance_band = "numeric_only"
            else:
                top_records = records_for(
                    f"{metric_key}_top3"
                )
                bottom_records = records_for(
                    f"{metric_key}_bottom4"
                )
                if (
                    top_records is None
                    or bottom_records is None
                ):
                    return None

                in_top = any(
                    item.get("institution_id") == target_id
                    for item in top_records
                )
                in_bottom = any(
                    item.get("institution_id") == target_id
                    for item in bottom_records
                )

                if in_top and in_bottom:
                    performance_band = "boundary_tie"
                elif in_top:
                    performance_band = "better"
                elif in_bottom:
                    performance_band = "worse"
                else:
                    performance_band = "middle"

            metric_facts.append(
                MainMetricFact(
                    metric_id=metric_id,
                    metric_name=str(
                        record["metric_name"]
                    ),
                    value=(
                        DeterministicQueryPlanExecutor
                        ._json_scalar(record["value"])
                    ),
                    unit=str(record["unit"]),
                    rank=rank,
                    performance_direction=(
                        performance_direction
                    ),
                    performance_band=performance_band,
                )
            )

        if institution_name is None:
            return None

        return MainMetricsOverviewFacts(
            subject=InstitutionRef(
                institution_id=target_id,
                institution_name=institution_name,
            ),
            period=period,
            metrics=metric_facts,
        )

    @staticmethod
    def _ranking_overview_facts(
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> RankingOverviewFacts | None:
        operations = query_plan.get("operations")
        if not isinstance(operations, list) or not operations:
            return None

        producers = {
            operation.get("output_ref"): operation
            for operation in operations
            if (
                isinstance(operation, dict)
                and isinstance(
                    operation.get("output_ref"),
                    str,
                )
            )
        }

        final_operation = operations[-1]
        if not isinstance(final_operation, dict):
            return None

        final_operator = final_operation.get(
            "operator_id"
        )

        if final_operator == "OP019":
            final_refs = final_operation.get(
                "input_refs"
            )
            if (
                not isinstance(final_refs, list)
                or not final_refs
                or not all(
                    isinstance(ref, str)
                    for ref in final_refs
                )
            ):
                return None
            selected_refs = list(final_refs)
        elif final_operator in {
            "OP011",
            "OP012",
            "OP013",
        }:
            output_ref = final_operation.get(
                "output_ref"
            )
            if not isinstance(output_ref, str):
                return None
            selected_refs = [output_ref]
        else:
            return None

        def records_for(
            output_ref: str,
        ) -> list[dict[str, Any]] | None:
            value = context.get(output_ref)
            if (
                not isinstance(value, ExecutionValue)
                or value.kind != "records"
                or not isinstance(value.data, list)
            ):
                return None

            records = [
                item
                for item in value.data
                if isinstance(item, dict)
            ]
            return records if records else None

        def ranking_lineage(
            selected_ref: str,
        ) -> tuple[
            str,
            dict[str, Any],
            dict[str, Any] | None,
        ] | None:
            selected_operation = producers.get(
                selected_ref
            )
            if not isinstance(
                selected_operation,
                dict,
            ):
                return None

            operator_id = selected_operation.get(
                "operator_id"
            )

            if operator_id in {"OP011", "OP012"}:
                return (
                    selected_ref,
                    selected_operation,
                    None,
                )

            if operator_id != "OP013":
                return None

            input_refs = selected_operation.get(
                "input_refs"
            )
            if (
                not isinstance(input_refs, list)
                or len(input_refs) != 1
                or not isinstance(input_refs[0], str)
            ):
                return None

            rank_ref = input_refs[0]
            rank_operation = producers.get(rank_ref)

            if (
                not isinstance(rank_operation, dict)
                or rank_operation.get("operator_id")
                not in {"OP011", "OP012"}
            ):
                return None

            return (
                rank_ref,
                rank_operation,
                selected_operation,
            )

        lineages: list[
            tuple[
                str,
                str,
                dict[str, Any],
                dict[str, Any] | None,
            ]
        ] = []

        for selected_ref in selected_refs:
            lineage = ranking_lineage(
                selected_ref
            )
            if lineage is None:
                return None

            rank_ref, rank_operation, take_operation = (
                lineage
            )
            lineages.append(
                (
                    selected_ref,
                    rank_ref,
                    rank_operation,
                    take_operation,
                )
            )

        institutions_plan = query_plan.get(
            "institutions"
        )
        targets = (
            institutions_plan.get("targets")
            if isinstance(
                institutions_plan,
                dict,
            )
            else []
        )
        targets = (
            targets
            if isinstance(targets, list)
            else []
        )

        target_ids = {
            item.get("institution_id")
            for item in targets
            if (
                isinstance(item, dict)
                and isinstance(
                    item.get("institution_id"),
                    str,
                )
            )
        }

        metrics_plan = query_plan.get("metrics")
        requested_metric_ids = (
            metrics_plan.get(
                "requested_metric_ids"
            )
            if isinstance(metrics_plan, dict)
            else []
        )
        requested_metric_ids = [
            metric_id
            for metric_id in requested_metric_ids
            if isinstance(metric_id, str)
        ]

        source_metric_ids = (
            metrics_plan.get(
                "source_metric_ids"
            )
            if isinstance(metrics_plan, dict)
            else []
        )
        source_metric_ids = [
            metric_id
            for metric_id in source_metric_ids
            if isinstance(metric_id, str)
        ]

        period_average_spec = None
        if len(requested_metric_ids) == 1:
            candidate = (
                _PERIOD_AVERAGE_FACT_METRICS.get(
                    requested_metric_ids[0]
                )
            )
            if (
                candidate is not None
                and candidate[
                    "source_metric_id"
                ]
                in source_metric_ids
            ):
                period_average_spec = {
                    **candidate,
                    "derived_metric_id": (
                        requested_metric_ids[0]
                    ),
                }

        grouped: dict[
            str,
            dict[str, Any],
        ] = {}

        take_directions: set[str] = set()
        take_sizes: set[int] = set()
        all_periods: set[
            tuple[str, str]
        ] = set()

        for (
            selected_ref,
            rank_ref,
            rank_operation,
            take_operation,
        ) in lineages:
            selected_records = records_for(
                selected_ref
            )
            ranked_records = records_for(rank_ref)

            if (
                selected_records is None
                or ranked_records is None
            ):
                return None

            rank_operator = rank_operation.get(
                "operator_id"
            )
            rank_parameters = rank_operation.get(
                "parameters"
            )
            rank_parameters = (
                rank_parameters
                if isinstance(rank_parameters, dict)
                else {}
            )

            if rank_operator == "OP012":
                performance_direction = (
                    rank_parameters.get(
                        "performance_direction"
                    )
                )
                if performance_direction not in {
                    "higher_is_better",
                    "lower_is_better",
                }:
                    return None
                ranking_method = "performance"
                ranking_order = None
            elif rank_operator == "OP011":
                order = rank_parameters.get(
                    "order"
                )
                if order not in {
                    "ascending",
                    "descending",
                }:
                    return None
                performance_direction = (
                    "not_applicable"
                )
                ranking_method = "numeric"
                ranking_order = order
            else:
                return None

            if take_operation is not None:
                take_parameters = take_operation.get(
                    "parameters"
                )
                take_parameters = (
                    take_parameters
                    if isinstance(
                        take_parameters,
                        dict,
                    )
                    else {}
                )
                direction = take_parameters.get(
                    "direction"
                )
                n = take_parameters.get("n")

                if direction not in {
                    "top",
                    "bottom",
                }:
                    return None
                if (
                    isinstance(n, bool)
                    or not isinstance(n, int)
                    or n < 1
                ):
                    return None

                take_directions.add(direction)
                take_sizes.add(n)

            def record_period(
                record: dict[str, Any],
            ) -> tuple[str, str] | None:
                data_date = record.get("date")
                if isinstance(data_date, str):
                    return (
                        data_date,
                        data_date,
                    )

                start_date = record.get(
                    "start_date"
                )
                end_date = record.get(
                    "end_date"
                )
                if (
                    isinstance(start_date, str)
                    and isinstance(end_date, str)
                ):
                    return (
                        start_date,
                        end_date,
                    )

                return None

            def fact_metric_id(
                record: dict[str, Any],
            ) -> str | None:
                metric_id = record.get(
                    "metric_id"
                )
                if not isinstance(metric_id, str):
                    return None

                if (
                    period_average_spec is not None
                    and record.get("date") is None
                    and metric_id
                    == period_average_spec[
                        "source_metric_id"
                    ]
                ):
                    return period_average_spec[
                        "derived_metric_id"
                    ]

                return metric_id

            full_groups: dict[
                tuple[
                    tuple[str, str],
                    str,
                ],
                list[dict[str, Any]],
            ] = defaultdict(list)

            for record in ranked_records:
                metric_id = fact_metric_id(
                    record
                )
                period_key = record_period(
                    record
                )

                if (
                    metric_id is None
                    or period_key is None
                ):
                    return None

                full_groups[
                    (period_key, metric_id)
                ].append(record)

            selected_groups: dict[
                tuple[
                    tuple[str, str],
                    str,
                ],
                list[dict[str, Any]],
            ] = defaultdict(list)

            for record in selected_records:
                metric_id = fact_metric_id(
                    record
                )
                period_key = record_period(
                    record
                )

                if (
                    metric_id is None
                    or period_key is None
                ):
                    return None

                selected_groups[
                    (period_key, metric_id)
                ].append(record)

            for (
                period_key,
                metric_id,
            ), selected_group in (
                selected_groups.items()
            ):
                full_group = full_groups.get(
                    (period_key, metric_id)
                )
                if not full_group:
                    return None

                all_periods.add(period_key)

                metric_names = {
                    item.get("metric_name")
                    for item in full_group
                }
                units = {
                    item.get("unit")
                    for item in full_group
                }

                if (
                    len(metric_names) != 1
                    or len(units) != 1
                ):
                    return None

                if (
                    period_average_spec is not None
                    and metric_id
                    == period_average_spec[
                        "derived_metric_id"
                    ]
                ):
                    metric_name = (
                        period_average_spec[
                            "metric_name"
                        ]
                    )
                else:
                    metric_name = next(
                        iter(metric_names)
                    )

                unit = next(iter(units))

                if (
                    not isinstance(metric_name, str)
                    or not isinstance(unit, str)
                ):
                    return None

                population_ids = {
                    item.get("institution_id")
                    for item in full_group
                    if isinstance(
                        item.get("institution_id"),
                        str,
                    )
                }
                if not population_ids:
                    return None

                group = grouped.get(metric_id)

                if group is None:
                    group = {
                        "metric_name": metric_name,
                        "unit": unit,
                        "performance_direction": (
                            performance_direction
                        ),
                        "ranking_method": (
                            ranking_method
                        ),
                        "ranking_order": (
                            ranking_order
                        ),
                        "population_size": len(
                            population_ids
                        ),
                        "items": {},
                    }
                    grouped[metric_id] = group
                elif (
                    group["metric_name"]
                    != metric_name
                    or group["unit"] != unit
                    or group[
                        "performance_direction"
                    ]
                    != performance_direction
                    or group["ranking_method"]
                    != ranking_method
                    or group["ranking_order"]
                    != ranking_order
                    or group["population_size"]
                    != len(population_ids)
                ):
                    return None

                items = group["items"]

                for record in selected_group:
                    institution_id = record.get(
                        "institution_id"
                    )
                    institution_name = record.get(
                        "institution_name"
                    )
                    value = record.get("value")
                    rank = record.get("rank")

                    if (
                        not isinstance(
                            institution_id,
                            str,
                        )
                        or not isinstance(
                            institution_name,
                            str,
                        )
                        or value is None
                        or isinstance(rank, bool)
                        or not isinstance(rank, int)
                        or rank < 1
                    ):
                        return None

                    current = (
                        institution_name,
                        value,
                        rank,
                    )
                    previous = items.get(
                        institution_id
                    )

                    if (
                        previous is not None
                        and previous != current
                    ):
                        return None

                    items[institution_id] = current

        if (
            not grouped
            or len(all_periods) != 1
        ):
            return None

        period_start, period_end = next(
            iter(all_periods)
        )
        period = period_end

        population_sizes = {
            int(group["population_size"])
            for group in grouped.values()
        }

        has_partial_take = (
            bool(take_sizes)
            and bool(population_sizes)
            and any(
                take_size < population_size
                for take_size in take_sizes
                for population_size
                in population_sizes
            )
        )

        if take_directions and (
            not target_ids
            or has_partial_take
        ):
            if (
                len(take_directions) != 1
                or len(take_sizes) != 1
            ):
                return None

            direction = next(
                iter(take_directions)
            )
            selection_mode = (
                "top_n"
                if direction == "top"
                else "bottom_n"
            )
            requested_n = next(iter(take_sizes))
        elif target_ids:
            selection_mode = "target"
            requested_n = None
        else:
            selection_mode = "full"
            requested_n = None

        ordered_metric_ids = [
            metric_id
            for metric_id in requested_metric_ids
            if metric_id in grouped
        ]
        ordered_metric_ids.extend(
            metric_id
            for metric_id in sorted(grouped)
            if metric_id
            not in ordered_metric_ids
        )

        rankings: list[
            MetricRankingFacts
        ] = []

        for metric_id in ordered_metric_ids:
            group = grouped[metric_id]
            raw_items = group["items"]

            selected_items = [
                (
                    institution_id,
                    institution_name,
                    value,
                    rank,
                )
                for (
                    institution_id,
                    (
                        institution_name,
                        value,
                        rank,
                    ),
                ) in raw_items.items()
                if (
                    not target_ids
                    or institution_id in target_ids
                )
            ]

            selected_items.sort(
                key=lambda item: (
                    item[3],
                    item[1],
                    item[0],
                )
            )

            if not selected_items:
                return None

            rankings.append(
                MetricRankingFacts(
                    metric=MetricRef(
                        metric_id=metric_id,
                        metric_name=group[
                            "metric_name"
                        ],
                        unit=group["unit"],
                        performance_direction=group[
                            "performance_direction"
                        ],
                    ),
                    items=[
                        RankingItem(
                            institution=InstitutionRef(
                                institution_id=(
                                    institution_id
                                ),
                                institution_name=(
                                    institution_name
                                ),
                            ),
                            value=(
                                DeterministicQueryPlanExecutor
                                ._json_scalar(value)
                            ),
                            rank=rank,
                        )
                        for (
                            institution_id,
                            institution_name,
                            value,
                            rank,
                        ) in selected_items
                    ],
                    population_size=group[
                        "population_size"
                    ],
                    ranking_method=group[
                        "ranking_method"
                    ],
                    ranking_order=group[
                        "ranking_order"
                    ],
                )
            )

        if not rankings:
            return None

        return RankingOverviewFacts(
            period=period,
            rankings=rankings,
            selection_mode=selection_mode,
            requested_n=requested_n,
            period_start=(
                period_start
                if period_start != period_end
                else None
            ),
            period_end=(
                period_end
                if period_start != period_end
                else None
            ),
        )

    @staticmethod
    def _extreme_metric_facts(
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> ExtremeMetricFacts | None:
        operations = query_plan.get("operations")
        if (
            not isinstance(operations, list)
            or not operations
        ):
            return None

        final_operation = operations[-1]
        if (
            not isinstance(final_operation, dict)
            or final_operation.get("operator_id")
            != "OP014"
        ):
            return None

        parameters = final_operation.get(
            "parameters"
        )
        parameters = (
            parameters
            if isinstance(parameters, dict)
            else {}
        )

        extreme_type = parameters.get("type")
        if extreme_type not in {"min", "max"}:
            return None

        output_ref = final_operation.get(
            "output_ref"
        )
        input_refs = final_operation.get(
            "input_refs"
        )

        if (
            not isinstance(output_ref, str)
            or not isinstance(input_refs, list)
            or len(input_refs) != 1
            or not isinstance(input_refs[0], str)
        ):
            return None

        result_value = context.get(output_ref)
        source_value = context.get(input_refs[0])

        if (
            not isinstance(result_value, ExecutionValue)
            or result_value.kind != "records"
            or not isinstance(result_value.data, list)
            or not isinstance(source_value, ExecutionValue)
            or source_value.kind != "records"
            or not isinstance(source_value.data, list)
        ):
            return None

        result_records = [
            item
            for item in result_value.data
            if isinstance(item, dict)
        ]
        source_records = [
            item
            for item in source_value.data
            if isinstance(item, dict)
        ]

        if (
            not result_records
            or not source_records
        ):
            return None

        metric_ids = {
            item.get("metric_id")
            for item in result_records
        }
        metric_names = {
            item.get("metric_name")
            for item in result_records
        }
        units = {
            item.get("unit")
            for item in result_records
        }
        periods = {
            item.get("date")
            for item in result_records
        }

        if (
            len(metric_ids) != 1
            or len(metric_names) != 1
            or len(units) != 1
            or len(periods) != 1
        ):
            return None

        metric_id = next(iter(metric_ids))
        metric_name = next(iter(metric_names))
        unit = next(iter(units))
        period = next(iter(periods))

        if not all(
            isinstance(value, str) and value
            for value in (
                metric_id,
                metric_name,
                unit,
                period,
            )
        ):
            return None

        try:
            extreme_values = {
                Decimal(str(item.get("value")))
                for item in result_records
                if item.get("value") is not None
            }
        except (
            InvalidOperation,
            ValueError,
        ):
            return None

        if len(extreme_values) != 1:
            return None

        source_population_ids = {
            item.get("institution_id")
            for item in source_records
            if (
                item.get("metric_id") == metric_id
                and item.get("date") == period
                and isinstance(
                    item.get("institution_id"),
                    str,
                )
            )
        }

        if not source_population_ids:
            return None

        seen_ids: set[str] = set()
        items: list[ExtremeMetricItem] = []

        for record in result_records:
            institution_id = record.get(
                "institution_id"
            )
            institution_name = record.get(
                "institution_name"
            )
            value = record.get("value")

            if (
                not isinstance(institution_id, str)
                or not isinstance(
                    institution_name,
                    str,
                )
                or not institution_name
                or value is None
                or institution_id
                not in source_population_ids
                or institution_id in seen_ids
            ):
                return None

            seen_ids.add(institution_id)
            items.append(
                ExtremeMetricItem(
                    institution=InstitutionRef(
                        institution_id=(
                            institution_id
                        ),
                        institution_name=(
                            institution_name
                        ),
                    ),
                    value=(
                        DeterministicQueryPlanExecutor
                        ._json_scalar(value)
                    ),
                )
            )

        items.sort(
            key=lambda item: (
                item.institution.institution_name,
                item.institution.institution_id
                or "",
            )
        )

        return ExtremeMetricFacts(
            metric_id=metric_id,
            metric_name=metric_name,
            unit=unit,
            period=period,
            extreme_type=extreme_type,
            items=items,
            population_size=len(
                source_population_ids
            ),
        )

    @staticmethod
    def _direct_metric_values_facts(
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> DirectMetricValuesFacts | None:
        operations = query_plan.get("operations")
        if (
            not isinstance(operations, list)
            or not operations
        ):
            return None

        producers: dict[
            str,
            dict[str, Any],
        ] = {}

        for operation in operations:
            if not isinstance(operation, dict):
                return None

            output_ref = operation.get("output_ref")
            operator_id = operation.get(
                "operator_id"
            )

            if (
                not isinstance(output_ref, str)
                or not isinstance(
                    operator_id,
                    str,
                )
                or output_ref in producers
            ):
                return None

            producers[output_ref] = operation

        final_operation = operations[-1]
        final_operator = final_operation.get(
            "operator_id"
        )
        final_ref = final_operation.get(
            "output_ref"
        )

        if not isinstance(final_ref, str):
            return None

        if final_operator == "OP001":
            if len(operations) != 1:
                return None

            selected_refs = [final_ref]

        elif final_operator == "OP019":
            input_refs = final_operation.get(
                "input_refs"
            )

            if (
                not isinstance(input_refs, list)
                or len(input_refs) < 2
                or not all(
                    isinstance(ref, str)
                    for ref in input_refs
                )
                or len(input_refs)
                != len(set(input_refs))
            ):
                return None

            direct_operations = operations[:-1]

            if any(
                operation.get("operator_id")
                != "OP001"
                for operation
                in direct_operations
            ):
                return None

            direct_output_refs = [
                operation.get("output_ref")
                for operation
                in direct_operations
            ]

            if (
                not all(
                    isinstance(ref, str)
                    for ref
                    in direct_output_refs
                )
                or len(direct_output_refs)
                != len(input_refs)
                or set(direct_output_refs)
                != set(input_refs)
            ):
                return None

            selected_refs = list(input_refs)

        else:
            return None

        metrics_plan = query_plan.get("metrics")
        if not isinstance(metrics_plan, dict):
            return None

        requested_metric_ids = (
            metrics_plan.get(
                "requested_metric_ids"
            )
        )
        source_metric_ids = metrics_plan.get(
            "source_metric_ids"
        )

        if (
            not isinstance(
                requested_metric_ids,
                list,
            )
            or not requested_metric_ids
            or not all(
                isinstance(metric_id, str)
                for metric_id
                in requested_metric_ids
            )
            or len(requested_metric_ids)
            != len(set(requested_metric_ids))
            or not isinstance(
                source_metric_ids,
                list,
            )
            or not all(
                isinstance(metric_id, str)
                for metric_id
                in source_metric_ids
            )
            or len(source_metric_ids)
            != len(set(source_metric_ids))
            or set(requested_metric_ids)
            != set(source_metric_ids)
        ):
            return None

        institutions_plan = query_plan.get(
            "institutions"
        )
        targets = (
            institutions_plan.get("targets")
            if isinstance(
                institutions_plan,
                dict,
            )
            else None
        )

        if (
            not isinstance(targets, list)
            or len(targets) != 1
            or not isinstance(targets[0], dict)
        ):
            return None

        planned_target_id = targets[0].get(
            "institution_id"
        )

        if not isinstance(
            planned_target_id,
            str,
        ):
            return None

        records_by_metric: dict[
            str,
            dict[str, Any],
        ] = {}

        institution_ids: set[str] = set()
        institution_names: set[str] = set()
        dates: set[str] = set()

        for output_ref in selected_refs:
            operation = producers.get(output_ref)

            if (
                not isinstance(operation, dict)
                or operation.get("operator_id")
                != "OP001"
            ):
                return None

            input_refs = operation.get(
                "input_refs"
            )
            parameters = operation.get(
                "parameters"
            )

            if (
                not isinstance(input_refs, list)
                or len(input_refs) != 1
                or not isinstance(
                    input_refs[0],
                    str,
                )
                or not isinstance(
                    parameters,
                    dict,
                )
                or not isinstance(
                    parameters.get("date"),
                    str,
                )
            ):
                return None

            planned_metric_id = input_refs[0]
            planned_date = parameters["date"]

            if parameters.get(
                "institution_id"
            ) != planned_target_id:
                return None

            value = context.get(output_ref)

            if (
                not isinstance(
                    value,
                    ExecutionValue,
                )
                or value.kind != "records"
                or not isinstance(
                    value.data,
                    list,
                )
                or len(value.data) != 1
                or not isinstance(
                    value.data[0],
                    dict,
                )
            ):
                return None

            record = value.data[0]

            institution_id = record.get(
                "institution_id"
            )
            institution_name = record.get(
                "institution_name"
            )
            data_date = record.get("date")
            metric_id = record.get("metric_id")
            metric_name = record.get(
                "metric_name"
            )
            unit = record.get("unit")
            metric_value = record.get("value")

            if (
                not isinstance(
                    institution_id,
                    str,
                )
                or not isinstance(
                    institution_name,
                    str,
                )
                or not isinstance(
                    data_date,
                    str,
                )
                or not isinstance(metric_id, str)
                or not isinstance(
                    metric_name,
                    str,
                )
                or not isinstance(unit, str)
                or metric_value is None
                or institution_id
                != planned_target_id
                or data_date != planned_date
                or metric_id
                != planned_metric_id
                or metric_id
                not in requested_metric_ids
                or metric_id
                in records_by_metric
            ):
                return None

            institution_ids.add(
                institution_id
            )
            institution_names.add(
                institution_name
            )
            dates.add(data_date)
            records_by_metric[
                metric_id
            ] = record

        if (
            set(records_by_metric)
            != set(requested_metric_ids)
            or len(institution_ids) != 1
            or len(institution_names) != 1
            or len(dates) != 1
        ):
            return None

        institution_id = next(
            iter(institution_ids)
        )
        institution_name = next(
            iter(institution_names)
        )
        period = next(iter(dates))

        return DirectMetricValuesFacts(
            subject=InstitutionRef(
                institution_id=institution_id,
                institution_name=(
                    institution_name
                ),
            ),
            period=period,
            metrics=[
                DirectMetricValueFact(
                    metric_id=metric_id,
                    metric_name=str(
                        records_by_metric[
                            metric_id
                        ]["metric_name"]
                    ),
                    value=(
                        DeterministicQueryPlanExecutor
                        ._json_scalar(
                            records_by_metric[
                                metric_id
                            ]["value"]
                        )
                    ),
                    unit=str(
                        records_by_metric[
                            metric_id
                        ]["unit"]
                    ),
                )
                for metric_id
                in requested_metric_ids
            ],
        )

    @staticmethod
    def _benchmark_comparison_facts(
        query_plan: dict[str, Any],
        final_value: ExecutionValue,
    ) -> BenchmarkComparisonFacts | None:
        operations = query_plan.get("operations")
        if not isinstance(operations, list) or not operations:
            return None
        final_operation = operations[-1]
        if (
            not isinstance(final_operation, dict)
            or final_operation.get("operator_id") != "OP003"
            or final_value.kind != "scalar"
            or final_value.data.get("operation") != "difference"
        ):
            return None
        input_refs = final_operation.get("input_refs")
        if not isinstance(input_refs, list) or len(input_refs) != 2:
            return None
        producers = {
            item.get("output_ref"): item
            for item in operations
            if isinstance(item, dict) and isinstance(item.get("output_ref"), str)
        }
        benchmark_operation = producers.get(input_refs[1])
        if (
            not isinstance(benchmark_operation, dict)
            or benchmark_operation.get("operator_id") != "OP010"
        ):
            return None

        left = final_value.data.get("left_record")
        right = final_value.data.get("right_record")
        if not isinstance(left, dict) or not isinstance(right, dict):
            return None
        required = (
            left.get("institution_name"),
            left.get("metric_id"),
            left.get("metric_name"),
            left.get("date"),
            left.get("unit"),
            left.get("value"),
            right.get("value"),
        )
        if any(item is None for item in required):
            return None
        if (
            right.get("institution_id") is not None
            or right.get("metric_id") != left.get("metric_id")
            or right.get("date") != left.get("date")
        ):
            return None

        metric_id = str(left["metric_id"])
        performance_directions = {
            "ZB001": "higher_is_better",
            "ZB002": "higher_is_better",
            "ZB011": "higher_is_better",
            "ZB012": "lower_is_better",
            "ZB013": "lower_is_better",
            "ZB015": "higher_is_better",
            "ZB016": "higher_is_better",
            "ZB017": "lower_is_better",
        }
        performance_direction = performance_directions.get(metric_id)
        if performance_direction is None:
            return None
        difference = Decimal(str(final_value.data.get("value")))
        relative_position = (
            "above" if difference > 0 else "below" if difference < 0 else "equal"
        )
        if difference == 0:
            assessment = "equal"
        elif performance_direction == "lower_is_better":
            assessment = "better" if difference < 0 else "worse"
        else:
            assessment = "better" if difference > 0 else "worse"
        unit = str(left["unit"])
        return BenchmarkComparisonFacts(
            subject=InstitutionRef(
                institution_id=(
                    str(left["institution_id"])
                    if left.get("institution_id") is not None
                    else None
                ),
                institution_name=str(left["institution_name"]),
            ),
            metric=MetricRef(
                metric_id=metric_id,
                metric_name=str(left["metric_name"]),
                unit=unit,
                performance_direction=performance_direction,
            ),
            period=str(left["date"]),
            target_value=DeterministicQueryPlanExecutor._json_scalar(left["value"]),
            benchmark_name=str(
                right.get("institution_name") or "全省13家农商行平均值"
            ).replace("均值", "平均值"),
            benchmark_value=DeterministicQueryPlanExecutor._json_scalar(
                right["value"]
            ),
            difference=DeterministicQueryPlanExecutor._json_scalar(difference),
            difference_unit="百分点" if unit == "%" else unit,
            relative_position=relative_position,
            performance_assessment=assessment,
        )

    @staticmethod
    def _json_scalar(value: object) -> JsonScalar:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _reconciliation_facts(
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> ReconciliationFacts | None:
        operations = query_plan.get(
            "operations"
        )

        if (
            not isinstance(operations, list)
            or not operations
        ):
            return None

        final_operation = operations[-1]

        if (
            not isinstance(final_operation, dict)
            or final_operation.get(
                "operator_id"
            )
            != "OP005"
        ):
            return None

        final_ref = final_operation.get(
            "output_ref"
        )
        input_refs = final_operation.get(
            "input_refs"
        )

        if (
            not isinstance(final_ref, str)
            or not isinstance(input_refs, list)
            or len(input_refs) < 2
            or not all(
                isinstance(ref, str)
                for ref in input_refs
            )
        ):
            return None

        final_value = context.get(final_ref)

        if (
            not isinstance(
                final_value,
                ExecutionValue,
            )
            or final_value.kind
            != "reconciliation"
            or not isinstance(
                final_value.data,
                dict,
            )
            or not isinstance(
                final_value.unit,
                str,
            )
            or not final_value.unit
        ):
            return None

        data = final_value.data

        for field_name in (
            "total_value",
            "component_sum",
            "difference",
        ):
            if data.get(field_name) is None:
                return None

        is_equal = data.get("is_equal")

        if not isinstance(is_equal, bool):
            return None

        total_input = context.get(
            input_refs[0]
        )

        if (
            not isinstance(
                total_input,
                ExecutionValue,
            )
            or total_input.kind != "records"
            or not isinstance(
                total_input.data,
                list,
            )
            or len(total_input.data) != 1
            or not isinstance(
                total_input.data[0],
                dict,
            )
        ):
            return None

        total_record = total_input.data[0]

        required_strings = (
            "institution_id",
            "institution_name",
            "date",
            "metric_name",
            "unit",
        )

        if any(
            not isinstance(
                total_record.get(field_name),
                str,
            )
            or not total_record[field_name]
            for field_name
            in required_strings
        ):
            return None

        if total_record.get("value") is None:
            return None

        if (
            total_record["unit"]
            != final_value.unit
        ):
            return None

        total_metric_name = (
            data.get("total_label")
            or total_record["metric_name"]
        )

        if (
            not isinstance(
                total_metric_name,
                str,
            )
            or not total_metric_name
        ):
            return None

        raw_components = data.get(
            "component_details"
        )

        if (
            not isinstance(
                raw_components,
                list,
            )
            or not raw_components
        ):
            return None

        components: list[
            ReconciliationComponentFact
        ] = []
        component_decimals: list[
            Decimal
        ] = []

        for raw_component in raw_components:
            if not isinstance(
                raw_component,
                dict,
            ):
                return None

            metric_name = raw_component.get(
                "metric_name"
            )
            value = raw_component.get("value")
            unit = raw_component.get("unit")

            if (
                not isinstance(
                    metric_name,
                    str,
                )
                or not metric_name
                or value is None
                or not isinstance(unit, str)
                or not unit
                or unit != final_value.unit
            ):
                return None

            try:
                component_decimal = Decimal(
                    str(value)
                )
            except (
                InvalidOperation,
                ValueError,
            ):
                return None

            component_decimals.append(
                component_decimal
            )
            components.append(
                ReconciliationComponentFact(
                    metric_name=metric_name,
                    value=(
                        DeterministicQueryPlanExecutor
                        ._json_scalar(value)
                    ),
                    unit=unit,
                )
            )

        try:
            total_decimal = Decimal(
                str(data["total_value"])
            )
            source_total_decimal = Decimal(
                str(total_record["value"])
            )
            component_sum_decimal = Decimal(
                str(data["component_sum"])
            )
            difference_decimal = Decimal(
                str(data["difference"])
            )
        except (
            InvalidOperation,
            ValueError,
        ):
            return None

        if total_decimal != source_total_decimal:
            return None

        if (
            sum(
                component_decimals,
                Decimal(0),
            )
            != component_sum_decimal
        ):
            return None

        if (
            total_decimal
            - component_sum_decimal
            != difference_decimal
        ):
            return None

        if (
            is_equal
            != (difference_decimal == 0)
        ):
            return None

        return ReconciliationFacts(
            subject=InstitutionRef(
                institution_id=str(
                    total_record[
                        "institution_id"
                    ]
                ),
                institution_name=str(
                    total_record[
                        "institution_name"
                    ]
                ),
            ),
            period=str(
                total_record["date"]
            ),
            total_metric_name=(
                total_metric_name
            ),
            total_value=(
                DeterministicQueryPlanExecutor
                ._json_scalar(
                    data["total_value"]
                )
            ),
            components=components,
            component_sum=(
                DeterministicQueryPlanExecutor
                ._json_scalar(
                    data["component_sum"]
                )
            ),
            difference=(
                DeterministicQueryPlanExecutor
                ._json_scalar(
                    data["difference"]
                )
            ),
            unit=final_value.unit,
            is_equal=is_equal,
        )

    @staticmethod
    def _calculated_metric_facts(
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> CalculatedMetricFacts | None:
        operations = query_plan.get("operations")

        if (
            not isinstance(operations, list)
            or len(operations) < 3
        ):
            return None

        calculation_types = {
            "OP003": "directional_difference",
            "OP004": "absolute_difference",
            "OP006": "ratio",
            "OP007": "growth_rate",
            "OP008": "percentage_point_change",
        }
        expected_operations = {
            "OP003": {"difference"},
            "OP004": {"absolute_difference"},
            "OP006": {"ratio", "quotient"},
            "OP007": {"growth_rate"},
            "OP008": {"percentage_point_change"},
        }
        roles = {
            "OP003": ("left", "right"),
            "OP004": ("left", "right"),
            "OP006": ("numerator", "denominator"),
            "OP007": ("current", "base"),
            "OP008": ("current", "base"),
        }

        final_operation = operations[-1]

        if not isinstance(final_operation, dict):
            return None

        final_operator = final_operation.get(
            "operator_id"
        )

        if final_operator not in calculation_types:
            return None

        final_ref = final_operation.get(
            "output_ref"
        )
        input_refs = final_operation.get(
            "input_refs"
        )
        parameters = final_operation.get(
            "parameters"
        )

        if (
            not isinstance(final_ref, str)
            or not isinstance(input_refs, list)
            or len(input_refs) != 2
            or not all(
                isinstance(ref, str)
                for ref in input_refs
            )
            or input_refs[0] == input_refs[1]
            or not isinstance(parameters, dict)
        ):
            return None

        producers: dict[
            str,
            dict[str, Any],
        ] = {}

        for operation in operations:
            if not isinstance(operation, dict):
                return None

            output_ref = operation.get(
                "output_ref"
            )

            if (
                not isinstance(output_ref, str)
                or output_ref in producers
            ):
                return None

            producers[output_ref] = operation

        read_operations: list[
            dict[str, Any]
        ] = []

        for input_ref in input_refs:
            producer = producers.get(input_ref)

            if (
                not isinstance(producer, dict)
                or producer.get("operator_id")
                != "OP001"
            ):
                return None

            read_operations.append(producer)

        relevant_refs = {
            final_ref,
            input_refs[0],
            input_refs[1],
        }

        for operation in operations:
            if (
                operation.get("output_ref")
                in relevant_refs
            ):
                continue

            if operation.get("operator_id") != "OP021":
                return None

        final_value = context.get(final_ref)

        if (
            not isinstance(final_value, ExecutionValue)
            or final_value.kind != "scalar"
            or not isinstance(
                final_value.data,
                dict,
            )
            or final_value.data.get("value")
            is None
        ):
            return None

        actual_operation = (
            final_value.data.get("operation")
            or final_value.metadata.get(
                "operation"
            )
        )

        if (
            actual_operation
            not in expected_operations[
                final_operator
            ]
        ):
            return None

        records: list[
            dict[str, Any]
        ] = []

        for input_ref, read_operation in zip(
            input_refs,
            read_operations,
            strict=True,
        ):
            execution_value = context.get(
                input_ref
            )

            if (
                not isinstance(
                    execution_value,
                    ExecutionValue,
                )
                or execution_value.kind
                != "records"
                or not isinstance(
                    execution_value.data,
                    list,
                )
                or len(execution_value.data)
                != 1
                or not isinstance(
                    execution_value.data[0],
                    dict,
                )
            ):
                return None

            record = execution_value.data[0]
            read_refs = read_operation.get(
                "input_refs"
            )
            read_parameters = (
                read_operation.get(
                    "parameters"
                )
            )

            if (
                not isinstance(read_refs, list)
                or len(read_refs) != 1
                or not isinstance(
                    read_refs[0],
                    str,
                )
                or not isinstance(
                    read_parameters,
                    dict,
                )
            ):
                return None

            required_strings = (
                "institution_id",
                "institution_name",
                "date",
                "metric_id",
                "metric_name",
                "unit",
            )

            if any(
                not isinstance(
                    record.get(field),
                    str,
                )
                for field in required_strings
            ):
                return None

            if record.get("value") is None:
                return None

            if (
                read_refs[0]
                != record["metric_id"]
                or read_parameters.get(
                    "institution_id"
                )
                != record["institution_id"]
                or read_parameters.get("date")
                != record["date"]
            ):
                return None

            records.append(record)

        institution_ids = {
            str(record["institution_id"])
            for record in records
        }
        institution_names = {
            str(record["institution_name"])
            for record in records
        }
        metric_ids = {
            str(record["metric_id"])
            for record in records
        }
        periods = {
            str(record["date"])
            for record in records
        }
        units = {
            str(record["unit"])
            for record in records
        }

        same_institution = (
            len(institution_ids) == 1
            and len(institution_names) == 1
        )
        cross_institution_comparison = (
            final_operator in {"OP003", "OP004"}
            and len(institution_ids) == 2
            and len(institution_names) == 2
            and len(metric_ids) == 1
            and len(periods) == 1
            and len(units) == 1
        )

        if (
            not same_institution
            and not cross_institution_comparison
        ):
            return None

        input_facts = [
            CalculationInputFact(
                role=role,
                metric_id=str(
                    record["metric_id"]
                ),
                metric_name=str(
                    record["metric_name"]
                ),
                period=str(record["date"]),
                value=(
                    DeterministicQueryPlanExecutor
                    ._json_scalar(
                        record["value"]
                    )
                ),
                unit=str(record["unit"]),
                institution=InstitutionRef(
                    institution_id=str(
                        record["institution_id"]
                    ),
                    institution_name=str(
                        record["institution_name"]
                    ),
                ),
            )
            for role, record in zip(
                roles[final_operator],
                records,
                strict=True,
            )
        ]

        result_metric_id = (
            final_value.metadata.get(
                "metric_id"
            )
            or parameters.get(
                "result_metric_id"
            )
        )

        if not isinstance(
            result_metric_id,
            str,
        ):
            result_metric_id = None

        result_metric_name = (
            final_value.metadata.get(
                "metric_name"
            )
            or parameters.get(
                "result_metric_name"
            )
        )

        left_name = str(
            records[0]["metric_name"]
        )
        right_name = str(
            records[1]["metric_name"]
        )

        if (
            not isinstance(
                result_metric_name,
                str,
            )
            or not result_metric_name
        ):
            if final_operator == "OP003":
                if left_name == right_name:
                    result_metric_name = (
                        f"{left_name}差额"
                        if cross_institution_comparison
                        else f"{left_name}变化额"
                    )
                else:
                    result_metric_name = (
                        f"{left_name}与"
                        f"{right_name}差额"
                    )
            elif final_operator == "OP004":
                if left_name == right_name:
                    result_metric_name = (
                        f"{left_name}绝对差额"
                        if cross_institution_comparison
                        else f"{left_name}绝对变化额"
                    )
                else:
                    result_metric_name = (
                        f"{left_name}与"
                        f"{right_name}绝对差额"
                    )
            elif final_operator == "OP006":
                result_metric_name = (
                    f"{left_name}占"
                    f"{right_name}比率"
                )
            elif final_operator == "OP007":
                result_metric_name = (
                    f"{left_name}增长率"
                )
            else:
                result_metric_name = (
                    f"{left_name}变化"
                )

        if (
            not isinstance(final_value.unit, str)
            or not final_value.unit
        ):
            return None

        subject = (
            InstitutionRef(
                institution_id=next(
                    iter(institution_ids)
                ),
                institution_name=next(
                    iter(institution_names)
                ),
            )
            if same_institution
            else InstitutionRef(
                institution_id=None,
                institution_name="两家机构",
            )
        )

        result_unit = final_value.unit
        if (
            cross_institution_comparison
            and len(units) == 1
            and next(iter(units)) == "%"
        ):
            result_unit = "百分点"

        return CalculatedMetricFacts(
            subject=subject,
            calculation_type=(
                calculation_types[
                    final_operator
                ]
            ),
            result_metric_id=result_metric_id,
            result_metric_name=(
                result_metric_name
            ),
            result_value=(
                DeterministicQueryPlanExecutor
                ._json_scalar(
                    final_value.data["value"]
                )
            ),
            result_unit=result_unit,
            inputs=input_facts,
        )

    def _dispatch(
        self,
        operator_id: str,
        input_refs: list[Any],
        parameters: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> ExecutionValue:
        if operator_id == "OP001":
            return self._op_read(input_refs, parameters)
        if operator_id == "OP021":
            return self._op_base_date(parameters)

        inputs = self._resolve_inputs(input_refs, context)
        handlers: dict[str, Callable[[list[ExecutionValue], dict[str, Any]], ExecutionValue]] = {
            "OP002": self._op_sum,
            "OP003": self._op_directional_difference,
            "OP004": self._op_absolute_difference,
            "OP005": self._op_reconcile,
            "OP006": self._op_ratio,
            "OP007": self._op_growth,
            "OP008": self._op_percentage_point_change,
            "OP009": self._op_period_average,
            "OP010": self._op_province_average,
            "OP011": self._op_numeric_sort,
            "OP012": self._op_performance_rank,
            "OP013": self._op_take_n,
            "OP014": self._op_extreme,
            "OP015": self._op_threshold,
            "OP016": self._op_filter,
            "OP017": self._op_count,
            "OP018": self._op_trend,
            "OP019": self._op_merge,
            "OP020": self._op_unit_conversion,
        }
        handler = handlers.get(operator_id)
        if handler is None:
            raise QueryExecutionError(f"确定性执行器暂不支持算子 {operator_id}。")
        return handler(inputs, parameters)

    @staticmethod
    def _resolve_inputs(
        input_refs: list[Any],
        context: dict[str, ExecutionValue],
    ) -> list[ExecutionValue]:
        resolved: list[ExecutionValue] = []
        for ref in input_refs:
            if not isinstance(ref, str) or ref not in context:
                raise QueryExecutionError(f"操作引用了尚未产生的结果：{ref!r}")
            resolved.append(context[ref])
        return resolved

    def _op_read(
        self,
        input_refs: list[Any],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        if len(input_refs) != 1 or not isinstance(input_refs[0], str):
            raise QueryExecutionError("OP001 必须接收一个正式指标编号。")
        metric_id = input_refs[0]

        institution_id = parameters.get("institution_id")
        institution_ids = parameters.get("institution_ids")
        if isinstance(institution_id, str):
            requested_institutions = [institution_id]
        elif isinstance(institution_ids, list) and all(
            isinstance(item, str) for item in institution_ids
        ):
            requested_institutions = list(institution_ids)
        else:
            raise QueryExecutionError("OP001 缺少合法机构参数。")

        records: list[dict[str, Any]] = []
        for current_institution in requested_institutions:
            sql, sql_parameters = self._build_read_sql(
                metric_id,
                current_institution,
                parameters,
            )
            result = self.database_executor.execute_query(
                sql,
                sql_parameters,
                max_rows=1000,
            )
            if result.truncated:
                raise QueryExecutionError("OP001 查询结果超过单机构1000行限制。")
            expected_columns = [
                "institution_id",
                "institution_name",
                "data_date",
                "metric_id",
                "metric_name",
                "metric_unit",
                "metric_value_scaled",
                "value_scale",
            ]
            if result.columns != expected_columns:
                raise QueryExecutionError("OP001 固定查询返回了非预期字段。")
            for row in result.rows:
                if len(row) != len(expected_columns):
                    raise QueryExecutionError("OP001 固定查询返回了非预期记录。")
                scaled = row[6]
                scale = row[7]
                if isinstance(scaled, bool) or not isinstance(scaled, int):
                    raise QueryExecutionError("数据库指标值不是整数缩放值。")
                if isinstance(scale, bool) or not isinstance(scale, int):
                    raise QueryExecutionError("数据库指标缩放位数不合法。")
                records.append(
                    {
                        "institution_id": row[0],
                        "institution_name": row[1],
                        "date": row[2],
                        "metric_id": row[3],
                        "metric_name": row[4],
                        "unit": row[5],
                        "value": Decimal(scaled) / (Decimal(10) ** scale),
                    }
                )

        if not records:
            raise QueryExecutionError("正式数据库中没有找到查询计划要求的记录。")
        records.sort(
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("institution_id") or ""),
                str(item.get("metric_id") or ""),
            )
        )
        units = {str(item["unit"]) for item in records if item.get("unit") is not None}
        return ExecutionValue(
            kind="records",
            data=records,
            unit=next(iter(units)) if len(units) == 1 else None,
        )

    @staticmethod
    def _build_read_sql(
        metric_id: str,
        institution_id: str,
        parameters: dict[str, Any],
    ) -> tuple[str, dict[str, JsonScalar]]:
        where = [
            "f.metric_id = :metric_id",
            "f.institution_id = :institution_id",
        ]
        sql_parameters: dict[str, JsonScalar] = {
            "metric_id": metric_id,
            "institution_id": institution_id,
        }

        if isinstance(parameters.get("date"), str):
            where.append("f.data_date = :data_date")
            sql_parameters["data_date"] = parameters["date"]
        elif isinstance(parameters.get("dates"), list) and parameters["dates"]:
            date_names: list[str] = []
            for index, value in enumerate(parameters["dates"]):
                if not isinstance(value, str):
                    raise QueryExecutionError("OP001.dates 必须全部为日期字符串。")
                name = f"date_{index}"
                date_names.append(f":{name}")
                sql_parameters[name] = value
            where.append(f"f.data_date IN ({', '.join(date_names)})")
        elif isinstance(parameters.get("start_date"), str) and isinstance(
            parameters.get("end_date"), str
        ):
            where.append("f.data_date BETWEEN :start_date AND :end_date")
            sql_parameters["start_date"] = parameters["start_date"]
            sql_parameters["end_date"] = parameters["end_date"]
        else:
            raise QueryExecutionError("OP001 缺少明确时间参数。")

        sql = (
            "SELECT f.institution_id AS institution_id, "
            "i.institution_name AS institution_name, "
            "f.data_date AS data_date, "
            "f.metric_id AS metric_id, "
            "m.metric_name AS metric_name, "
            "m.metric_unit AS metric_unit, "
            "f.metric_value_scaled AS metric_value_scaled, "
            "m.value_scale AS value_scale "
            "FROM metric_facts AS f "
            "JOIN institutions AS i ON i.institution_id = f.institution_id "
            "JOIN metrics AS m ON m.metric_id = f.metric_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY f.data_date, f.institution_id"
        )
        return sql, sql_parameters

    def _op_sum(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        if not inputs:
            raise QueryExecutionError("OP002 至少需要一个输入。")
        result = inputs[0]
        for current in inputs[1:]:
            result = self._binary_transform(result, current, operator.add, "sum")
        return result

    def _op_directional_difference(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 2, "OP003")
        return self._binary_transform(inputs[0], inputs[1], operator.sub, "difference")

    def _op_absolute_difference(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 2, "OP004")
        return self._binary_transform(
            inputs[0],
            inputs[1],
            lambda left, right: abs(left - right),
            "absolute_difference",
        )

    def _op_reconcile(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        if len(inputs) < 2:
            raise QueryExecutionError("OP005 至少需要总量和一个分项输入。")

        total, total_unit = self._single_numeric(inputs[0])
        components: list[Decimal] = []
        component_units: list[str | None] = []
        component_details: list[dict[str, Any]] = []

        total_label: str | None = None
        if inputs[0].kind == "records":
            total_records = self._records(inputs[0])
            if len(total_records) == 1:
                raw_label = total_records[0].get("metric_name")
                if isinstance(raw_label, str):
                    total_label = raw_label

        for value in inputs[1:]:
            numeric, unit = self._single_numeric(value)
            components.append(numeric)
            component_units.append(unit)

            source_records: list[dict[str, Any]] = []
            if value.kind == "records":
                records = self._records(value)
                if len(records) == 1:
                    source_records = records
            elif (
                value.kind == "scalar"
                and value.data.get("operation") == "sum"
            ):
                source_records = [
                    record
                    for key in ("left_record", "right_record")
                    if isinstance(
                        record := value.data.get(key),
                        dict,
                    )
                ]

            for record in source_records:
                name = record.get("metric_name")
                raw_value = record.get("value")
                raw_unit = record.get("unit") or unit
                if (
                    isinstance(name, str)
                    and raw_value is not None
                ):
                    component_details.append(
                        {
                            "metric_name": name,
                            "value": raw_value,
                            "unit": raw_unit,
                        }
                    )

        self._require_same_unit(
            [total_unit, *component_units],
            "OP005",
        )
        component_sum = sum(components, Decimal(0))
        difference = total - component_sum

        return ExecutionValue(
            kind="reconciliation",
            data={
                "total_label": total_label,
                "total_value": total,
                "component_details": component_details,
                "component_sum": component_sum,
                "difference": difference,
                "is_equal": difference == 0,
            },
            unit=total_unit,
        )

    def _op_ratio(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 2, "OP006")
        result_unit_raw = parameters.get("result_unit") or parameters.get("unit")
        result_unit = str(result_unit_raw) if result_unit_raw is not None else "%"
        multiplier_raw = parameters.get("multiplier")
        if multiplier_raw is None:
            multiplier = Decimal(100) if result_unit == "%" else Decimal(1)
        else:
            multiplier = self._decimal(multiplier_raw, "OP006.multiplier")
        if multiplier <= 0:
            raise QueryExecutionError("OP006.multiplier 必须大于0。")

        result_metric_id, result_metric_name = self._ratio_metric_metadata(
            inputs,
            parameters,
        )
        return self._binary_transform(
            inputs[0],
            inputs[1],
            lambda numerator, denominator: self._quotient(
                numerator,
                denominator,
                multiplier,
            ),
            "ratio" if result_unit == "%" else "quotient",
            result_unit=result_unit,
            require_same_unit=False,
            cross_metric_alignment=True,
            result_metric_id=result_metric_id,
            result_metric_name=result_metric_name,
        )

    def _ratio_metric_metadata(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        explicit_id = parameters.get("result_metric_id")
        explicit_name = parameters.get("result_metric_name")
        if isinstance(explicit_id, str) or isinstance(explicit_name, str):
            return (
                explicit_id if isinstance(explicit_id, str) else None,
                explicit_name if isinstance(explicit_name, str) else None,
            )

        def single_metric_id(value: ExecutionValue) -> str | None:
            if value.kind != "records":
                return None
            ids = {
                str(item.get("metric_id"))
                for item in self._records(value)
                if isinstance(item.get("metric_id"), str)
            }
            return next(iter(ids)) if len(ids) == 1 else None

        numerator_id = single_metric_id(inputs[0])
        denominator_id = single_metric_id(inputs[1])
        known = {
            ("ZB002", "ZB001"): ("ZB022", "存贷比"),
            ("ZB008", "ZB009"): (
                "ZB034",
                "净利息收入占营业收入比重",
            ),
            ("ZB007", "ZB009"): (
                None,
                "中间业务收入占营业收入比重",
            ),
        }
        return known.get((numerator_id, denominator_id), (None, None))

    def _op_growth(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 2, "OP007")
        return self._binary_transform(
            inputs[0],
            inputs[1],
            self._growth,
            "growth_rate",
            result_unit="%",
        )

    def _op_percentage_point_change(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 2, "OP008")
        return self._binary_transform(
            inputs[0],
            inputs[1],
            operator.sub,
            "percentage_point_change",
            result_unit="百分点",
        )

    def _op_period_average(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        records, input_unit = self._combined_records(inputs, "OP009")
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[
                (
                    record.get("institution_id"),
                    record.get("institution_name"),
                    record.get("metric_id"),
                    record.get("metric_name"),
                    record.get("unit"),
                )
            ].append(record)
        output: list[dict[str, Any]] = []
        for key, group in grouped.items():
            values = [self._decimal(item.get("value"), "OP009") for item in group]
            output.append(
                {
                    "institution_id": key[0],
                    "institution_name": key[1],
                    "date": None,
                    "metric_id": key[2],
                    "metric_name": key[3],
                    "unit": key[4],
                    "value": sum(values, Decimal(0)) / Decimal(len(values)),
                    "start_date": min(str(item["date"]) for item in group),
                    "end_date": max(str(item["date"]) for item in group),
                    "record_count": len(group),
                }
            )
        return ExecutionValue(kind="records", data=output, unit=input_unit)

    def _op_province_average(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP010")
        records = self._records(inputs[0])
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[
                (
                    record.get("date"),
                    record.get("metric_id"),
                    record.get("metric_name"),
                    record.get("unit"),
                )
            ].append(record)
        output: list[dict[str, Any]] = []
        for key, group in grouped.items():
            values = [self._decimal(item.get("value"), "OP010") for item in group]
            output.append(
                {
                    "institution_id": None,
                    "institution_name": "全省13家农商行均值",
                    "date": key[0],
                    "metric_id": key[1],
                    "metric_name": key[2],
                    "unit": key[3],
                    "value": sum(values, Decimal(0)) / Decimal(len(values)),
                    "institution_count": len(
                        {item.get("institution_id") for item in group}
                    ),
                }
            )
        output.sort(key=lambda item: str(item.get("date") or ""))
        return ExecutionValue(kind="records", data=output, unit=inputs[0].unit)

    def _op_numeric_sort(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        records, _ = self._combined_records(inputs, "OP011")
        order = parameters.get("order")
        if order not in {"ascending", "descending"}:
            raise QueryExecutionError("OP011.order 不合法。")
        return self._rank_records(
            records,
            reverse=order == "descending",
        )

    def _op_performance_rank(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        records, _ = self._combined_records(inputs, "OP012")
        direction = parameters.get("performance_direction")
        if direction not in {"higher_is_better", "lower_is_better"}:
            raise QueryExecutionError("OP012.performance_direction 不合法。")
        return self._rank_records(
            records,
            reverse=direction == "higher_is_better",
        )

    def _combined_records(
        self,
        inputs: list[ExecutionValue],
        operator_id: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not inputs:
            raise QueryExecutionError(f"{operator_id} 至少需要1个输入。")
        records: list[dict[str, Any]] = []
        units: set[str] = set()
        for value in inputs:
            current_records = self._records(value)
            records.extend(dict(item) for item in current_records)
            if value.unit:
                units.add(str(value.unit))
            units.update(
                str(item.get("unit"))
                for item in current_records
                if item.get("unit") is not None
            )
        if not records:
            raise QueryExecutionError(f"{operator_id} 没有可处理的记录。")
        if len(units) > 1:
            raise QueryExecutionError(f"{operator_id} 输入记录单位不一致。")
        return records, next(iter(units)) if units else None

    def _op_take_n(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP013")
        records = self._records(inputs[0])
        n = parameters.get("n")
        direction = parameters.get("direction")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise QueryExecutionError("OP013.n 必须是正整数。")
        if direction not in {"top", "bottom"}:
            raise QueryExecutionError("OP013.direction 不合法。")

        output: list[dict[str, Any]] = []
        for _, group in self._group_rank_records(records).items():
            if not group:
                continue
            if len(group) <= n:
                selected = group
            elif direction == "top":
                boundary = self._decimal(group[n - 1].get("value"), "OP013")
                selected = [
                    item
                    for item in group
                    if self._decimal(item.get("value"), "OP013") == boundary
                    or item in group[:n]
                ]
            else:
                ranks = [
                    item.get("rank")
                    for item in group
                ]
                if all(
                    isinstance(rank, int)
                    and not isinstance(rank, bool)
                    for rank in ranks
                ):
                    threshold_rank = len(group) - n + 1
                    selected = [
                        item
                        for item in group
                        if int(item["rank"]) >= threshold_rank
                    ]
                else:
                    boundary_index = len(group) - n
                    boundary = self._decimal(
                        group[boundary_index].get("value"),
                        "OP013",
                    )
                    selected = [
                        item
                        for item in group
                        if item in group[boundary_index:]
                        or self._decimal(
                            item.get("value"),
                            "OP013",
                        )
                        == boundary
                    ]
            output.extend(selected)
        return ExecutionValue(kind="records", data=output, unit=inputs[0].unit)

    def _op_extreme(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP014")
        records = self._records(inputs[0])
        extreme_type = parameters.get("type")
        if extreme_type not in {"max", "min"}:
            raise QueryExecutionError("OP014.type 必须是 max 或 min。")
        values = [self._decimal(item.get("value"), "OP014") for item in records]
        extreme = max(values) if extreme_type == "max" else min(values)
        selected: list[dict[str, Any]] = []
        result_type = "maximum" if extreme_type == "max" else "minimum"
        for item in records:
            if self._decimal(item.get("value"), "OP014") != extreme:
                continue
            current = dict(item)
            current["result_type"] = result_type
            selected.append(current)
        return ExecutionValue(
            kind="records",
            data=selected,
            unit=inputs[0].unit,
            metadata={"result_type": result_type},
        )

    def _op_threshold(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP015")
        value, input_unit = self._single_numeric(inputs[0])
        threshold = self._decimal(parameters.get("threshold"), "OP015")
        comparison_operator = parameters.get("comparison_operator")
        is_met = self._compare(value, threshold, comparison_operator)
        if comparison_operator in {"<", "<="}:
            gap = threshold - value
        elif comparison_operator in {">", ">="}:
            gap = value - threshold
        else:
            gap = abs(value - threshold)
        return ExecutionValue(
            kind="assessment",
            data={
                "metric_value": value,
                "threshold": threshold,
                "comparison_operator": comparison_operator,
                "is_met": is_met,
                "gap": gap,
            },
            unit=str(parameters.get("unit") or input_unit or ""),
        )

    def _op_filter(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP016")
        records = self._records(inputs[0])
        threshold = self._decimal(parameters.get("threshold"), "OP016")
        comparison_operator = parameters.get("comparison_operator")
        selected = [
            dict(item)
            for item in records
            if self._compare(
                self._decimal(item.get("value"), "OP016"),
                threshold,
                comparison_operator,
            )
        ]
        count_by, count_unit = self._infer_count_dimension(records)
        if count_by == "date":
            population_count = len(
                {
                    item.get("date")
                    for item in records
                    if item.get("date") is not None
                }
            )
        elif count_by == "institution":
            population_count = len(
                {
                    item.get("institution_id")
                    for item in records
                    if item.get("institution_id") is not None
                }
            )
        else:
            population_count = len(records)
        return ExecutionValue(
            kind="records",
            data=selected,
            unit=inputs[0].unit,
            metadata={
                "count_by": count_by,
                "count_unit": count_unit,
                "population_count": population_count,
            },
        )

    @staticmethod
    def _infer_count_dimension(
        records: list[dict[str, Any]],
    ) -> tuple[str, str]:
        dates = {
            item.get("date")
            for item in records
            if item.get("date") is not None
        }
        institutions = {
            item.get("institution_id")
            for item in records
            if item.get("institution_id") is not None
        }
        if len(dates) > 1 and len(institutions) <= 1:
            return "date", "天"
        if len(institutions) > 1 and len(dates) <= 1:
            return "institution", "家"
        return "record", "条"

    def _op_count(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP017")
        value = inputs[0]
        requested_count_by = parameters.get("count_by")
        count_by = (
            requested_count_by
            if requested_count_by in {"date", "institution", "record"}
            else value.metadata.get("count_by")
        )
        if count_by not in {"date", "institution", "record"}:
            count_by = "record"

        if value.kind == "records":
            records = self._records(value)
            if count_by == "date":
                count = len(
                    {
                        item.get("date")
                        for item in records
                        if item.get("date") is not None
                    }
                )
            elif count_by == "institution":
                count = len(
                    {
                        item.get("institution_id")
                        for item in records
                        if item.get("institution_id") is not None
                    }
                )
            else:
                count = len(records)
        elif value.kind == "composite":
            count = len(value.data.get("items", []))
        elif isinstance(value.data, list):
            count = len(value.data)
        else:
            count = 1

        unit = parameters.get("unit")
        if not isinstance(unit, str) or not unit:
            unit = value.metadata.get("count_unit")
        if not isinstance(unit, str) or not unit:
            unit = {
                "date": "天",
                "institution": "家",
                "record": "条",
            }[count_by]
        population_count = value.metadata.get("population_count")
        share_percent: Decimal | None = None
        if (
            isinstance(population_count, int)
            and population_count > 0
            and count_by == "date"
        ):
            share_percent = (
                Decimal(count)
                / Decimal(population_count)
                * Decimal(100)
            )
        return ExecutionValue(
            kind="count",
            data={
                "count": count,
                "count_by": count_by,
                "population_count": population_count,
                "share_percent": share_percent,
            },
            unit=unit,
            metadata={
                "count_by": count_by,
                "count_unit": unit,
                "population_count": population_count,
            },
        )

    def _op_trend(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP018")
        records = self._records(inputs[0])
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[
                (
                    record.get("institution_id"),
                    record.get("metric_id"),
                )
            ].append(record)
        trends: list[dict[str, Any]] = []
        for key, group in grouped.items():
            ordered = sorted(group, key=lambda item: str(item.get("date") or ""))
            values = [self._decimal(item.get("value"), "OP018") for item in ordered]
            trends.append(
                {
                    "institution_id": key[0],
                    "metric_id": key[1],
                    "trend": self._classify_trend(values),
                }
            )
        return ExecutionValue(
            kind="trend",
            data={"series": records, "trends": trends},
            unit=inputs[0].unit,
        )

    def _op_merge(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        if len(inputs) < 2:
            raise QueryExecutionError("OP019 至少需要两个输入。")
        return ExecutionValue(
            kind="composite",
            data={"items": inputs},
            unit=None,
        )

    def _op_unit_conversion(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP020")
        source_unit = parameters.get("from_unit") or inputs[0].unit
        target_unit = parameters.get("to_unit")
        factor_raw = parameters.get("factor")
        if factor_raw is not None:
            factor = self._decimal(factor_raw, "OP020")
        else:
            known = {
                ("亿元", "万元"): Decimal(10000),
                ("万元", "亿元"): Decimal("0.0001"),
            }
            factor = known.get((source_unit, target_unit))
            if factor is None:
                raise QueryExecutionError("OP020 缺少可执行的单位换算规则。")
        value = inputs[0]
        if value.kind == "records":
            records = []
            for item in self._records(value):
                converted = dict(item)
                converted["value"] = self._decimal(item.get("value"), "OP020") * factor
                converted["unit"] = target_unit
                records.append(converted)
            return ExecutionValue(kind="records", data=records, unit=str(target_unit))
        numeric, _ = self._single_numeric(value)
        return ExecutionValue(
            kind="scalar",
            data={"value": numeric * factor},
            unit=str(target_unit),
        )

    def _op_base_date(self, parameters: dict[str, Any]) -> ExecutionValue:
        base_type = parameters.get("type")
        reference_raw = parameters.get("reference_date")
        if not isinstance(reference_raw, str):
            raise QueryExecutionError("OP021 缺少 reference_date。")
        try:
            reference = date.fromisoformat(reference_raw)
        except ValueError as exc:
            raise QueryExecutionError("OP021.reference_date 不是合法日期。") from exc

        if base_type == "previous_month_end":
            year = reference.year
            month = reference.month - 1
            if month == 0:
                year -= 1
                month = 12
            resolved = date(year, month, calendar.monthrange(year, month)[1])
        elif base_type == "previous_quarter_end":
            quarter = (reference.month - 1) // 3 + 1
            if quarter == 1:
                resolved = date(reference.year - 1, 12, 31)
            else:
                month = (quarter - 1) * 3
                resolved = date(
                    reference.year,
                    month,
                    calendar.monthrange(reference.year, month)[1],
                )
        elif base_type == "previous_year_same_period":
            previous_year = reference.year - 1
            if reference.day == calendar.monthrange(reference.year, reference.month)[1]:
                resolved = date(
                    previous_year,
                    reference.month,
                    calendar.monthrange(previous_year, reference.month)[1],
                )
            else:
                try:
                    resolved = reference.replace(year=previous_year)
                except ValueError:
                    resolved = date(previous_year, 2, 28)
        elif base_type in {"previous_year_end", "year_begin_base"}:
            resolved = date(reference.year - 1, 12, 31)
        else:
            raise QueryExecutionError("OP021.type 不合法。")
        return ExecutionValue(kind="date", data={"date": resolved.isoformat()})

    def _binary_transform(
        self,
        left: ExecutionValue,
        right: ExecutionValue,
        function: Callable[[Decimal, Decimal], Decimal],
        result_name: str,
        result_unit: str | None = None,
        require_same_unit: bool = True,
        cross_metric_alignment: bool = False,
        result_metric_id: str | None = None,
        result_metric_name: str | None = None,
    ) -> ExecutionValue:
        if left.kind == "records" and right.kind == "records":
            left_records = self._records(left)
            right_records = self._records(right)
            if len(left_records) == len(right_records) == 1:
                left_record = left_records[0]
                right_record = right_records[0]
                left_value = self._decimal(
                    left_record.get("value"),
                    result_name,
                )
                right_value = self._decimal(
                    right_record.get("value"),
                    result_name,
                )
                if require_same_unit:
                    self._require_same_unit(
                        [
                            left_record.get("unit"),
                            right_record.get("unit"),
                        ],
                        result_name,
                    )
                inferred_metric_name = result_metric_name
                if (
                    inferred_metric_name is None
                    and left_record.get("metric_id")
                    == right_record.get("metric_id")
                ):
                    inferred_metric_name = left_record.get("metric_name")
                metadata = {
                    "operation": result_name,
                    "metric_id": result_metric_id,
                    "metric_name": inferred_metric_name,
                }
                return ExecutionValue(
                    kind="scalar",
                    data={
                        "value": function(left_value, right_value),
                        "left_value": left_value,
                        "right_value": right_value,
                        "left_record": dict(left_record),
                        "right_record": dict(right_record),
                        "operation": result_name,
                    },
                    unit=result_unit or left_record.get("unit"),
                    metadata=metadata,
                )
            return self._aligned_record_transform(
                left_records,
                right_records,
                function,
                result_unit=result_unit,
                require_same_unit=require_same_unit,
                cross_metric_alignment=cross_metric_alignment,
                result_metric_id=result_metric_id,
                result_metric_name=result_metric_name,
            )

        left_value, left_unit = self._single_numeric(left)
        right_value, right_unit = self._single_numeric(right)
        if require_same_unit:
            self._require_same_unit([left_unit, right_unit], result_name)
        return ExecutionValue(
            kind="scalar",
            data={
                "value": function(left_value, right_value),
                "left_value": left_value,
                "right_value": right_value,
                "operation": result_name,
            },
            unit=result_unit or left_unit,
            metadata={
                "operation": result_name,
                "metric_id": result_metric_id,
                "metric_name": result_metric_name,
            },
        )

    def _aligned_record_transform(
        self,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        function: Callable[[Decimal, Decimal], Decimal],
        result_unit: str | None,
        require_same_unit: bool,
        cross_metric_alignment: bool = False,
        result_metric_id: str | None = None,
        result_metric_name: str | None = None,
    ) -> ExecutionValue:
        def unique_map(
            records: list[dict[str, Any]],
            fields: tuple[str, ...],
        ) -> dict[tuple[Any, ...], dict[str, Any]] | None:
            result: dict[tuple[Any, ...], dict[str, Any]] = {}
            for record in records:
                key = tuple(record.get(field) for field in fields)
                if key in result:
                    return None
                result[key] = record
            return result

        def transform_pairs(
            pairs: list[tuple[dict[str, Any], dict[str, Any]]],
        ) -> ExecutionValue:
            output: list[dict[str, Any]] = []
            for left_record, right_record in pairs:
                if require_same_unit:
                    self._require_same_unit(
                        [left_record.get("unit"), right_record.get("unit")],
                        "aligned operation",
                    )
                left_value = self._decimal(
                    left_record.get("value"),
                    "aligned operation",
                )
                right_value = self._decimal(
                    right_record.get("value"),
                    "aligned operation",
                )
                current = dict(left_record)
                if result_metric_id is not None:
                    current["metric_id"] = result_metric_id
                if result_metric_name is not None:
                    current["metric_name"] = result_metric_name
                current["left_value"] = left_value
                current["right_value"] = right_value
                current["left_date"] = left_record.get("date")
                current["right_date"] = right_record.get("date")
                current["value"] = function(left_value, right_value)
                if result_unit is not None:
                    current["unit"] = result_unit
                output.append(current)
            return ExecutionValue(
                kind="records",
                data=output,
                unit=result_unit or left_records[0].get("unit"),
                metadata={
                    "metric_id": result_metric_id,
                    "metric_name": result_metric_name,
                },
            )

        exact_fields = ("institution_id", "date", "metric_id")
        left_exact = unique_map(left_records, exact_fields)
        right_exact = unique_map(right_records, exact_fields)
        if (
            left_exact is not None
            and right_exact is not None
            and set(left_exact) == set(right_exact)
        ):
            return transform_pairs(
                [(left_exact[key], right_exact[key]) for key in left_exact]
            )

        if cross_metric_alignment:
            cross_metric_fields = (
                ("institution_id", "date"),
                ("institution_id", "start_date", "end_date"),
                ("institution_id",),
            )
            for fields in cross_metric_fields:
                left_map = unique_map(left_records, fields)
                right_map = unique_map(right_records, fields)
                if (
                    left_map is not None
                    and right_map is not None
                    and set(left_map) == set(right_map)
                ):
                    return transform_pairs(
                        [
                            (left_map[key], right_map[key])
                            for key in left_map
                        ]
                    )

        period_fields = ("institution_id", "metric_id")
        left_period = unique_map(left_records, period_fields)
        right_period = unique_map(right_records, period_fields)
        if (
            left_period is not None
            and right_period is not None
            and set(left_period) == set(right_period)
        ):
            return transform_pairs(
                [(left_period[key], right_period[key]) for key in left_period]
            )

        baseline_fields = ("date", "metric_id")
        right_baseline = unique_map(right_records, baseline_fields)
        if right_baseline is not None:
            pairs = []
            for left_record in left_records:
                key = tuple(left_record.get(field) for field in baseline_fields)
                baseline = right_baseline.get(key)
                if baseline is None:
                    pairs = []
                    break
                pairs.append((left_record, baseline))
            if pairs:
                return transform_pairs(pairs)

        left_baseline = unique_map(left_records, baseline_fields)
        if left_baseline is not None:
            pairs = []
            for right_record in right_records:
                key = tuple(right_record.get(field) for field in baseline_fields)
                baseline = left_baseline.get(key)
                if baseline is None:
                    pairs = []
                    break
                pairs.append((baseline, right_record))
            if pairs:
                return transform_pairs(pairs)

        raise QueryExecutionError(
            "两个记录集合无法按机构、日期或比较期间对齐。"
        )

    @staticmethod
    def _quotient(
        numerator: Decimal,
        denominator: Decimal,
        multiplier: Decimal,
    ) -> Decimal:
        if denominator == 0:
            raise QueryExecutionError("除法计算分母为0。")
        return numerator / denominator * multiplier

    @staticmethod
    def _growth(current: Decimal, base: Decimal) -> Decimal:
        if base == 0:
            raise QueryExecutionError("增幅计算基期值为0。")
        return (current - base) / base * Decimal(100)

    @staticmethod
    def _compare(left: Decimal, right: Decimal, symbol: Any) -> bool:
        mapping: dict[str, Callable[[Decimal, Decimal], bool]] = {
            ">": operator.gt,
            ">=": operator.ge,
            "<": operator.lt,
            "<=": operator.le,
            "=": operator.eq,
            "!=": operator.ne,
        }
        function = mapping.get(symbol)
        if function is None:
            raise QueryExecutionError("比较符不合法。")
        return function(left, right)

    def _rank_records(
        self,
        records: list[dict[str, Any]],
        reverse: bool,
    ) -> ExecutionValue:
        output: list[dict[str, Any]] = []
        grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[(record.get("date"), record.get("metric_id"))].append(record)
        for key in sorted(grouped, key=lambda item: (str(item[0] or ""), str(item[1] or ""))):
            group = sorted(
                grouped[key],
                key=lambda item: self._decimal(item.get("value"), "ranking"),
                reverse=reverse,
            )
            previous_value: Decimal | None = None
            previous_rank = 0
            for index, record in enumerate(group, start=1):
                value = self._decimal(record.get("value"), "ranking")
                if previous_value is None or value != previous_value:
                    previous_rank = index
                    previous_value = value
                ranked = dict(record)
                ranked["rank"] = previous_rank
                output.append(ranked)
        return ExecutionValue(
            kind="records",
            data=output,
            unit=records[0].get("unit") if records else None,
        )

    @staticmethod
    def _group_rank_records(
        records: list[dict[str, Any]],
    ) -> dict[tuple[Any, Any], list[dict[str, Any]]]:
        grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[(record.get("date"), record.get("metric_id"))].append(record)
        return grouped

    @staticmethod
    def _classify_trend(values: list[Decimal]) -> str:
        if len(values) < 2:
            return "数据点不足"
        signs: list[int] = []
        for left, right in zip(values, values[1:]):
            difference = right - left
            signs.append(1 if difference > 0 else -1 if difference < 0 else 0)
        nonzero = [item for item in signs if item != 0]
        if not nonzero:
            return "持平"
        if all(item > 0 for item in nonzero):
            return "持续上升"
        if all(item < 0 for item in nonzero):
            return "持续下降"
        compressed = [nonzero[0]]
        for item in nonzero[1:]:
            if item != compressed[-1]:
                compressed.append(item)
        if compressed == [1, -1]:
            return "先升后降"
        if compressed == [-1, 1]:
            return "先降后升"
        return "存在波动"

    def _run_checks(
        self,
        query_plan: dict[str, Any],
        context: dict[str, ExecutionValue],
    ) -> None:
        checks = query_plan.get("checks")
        if not isinstance(checks, list):
            raise QueryExecutionError("查询计划 checks 格式错误。")
        source_records = [
            record
            for value in context.values()
            if value.operator_id == "OP001" and value.kind == "records"
            for record in self._records(value)
        ]

        for check in checks:
            if not isinstance(check, dict):
                raise QueryExecutionError("查询计划包含非法检查节点。")
            check_type = check.get("type")
            parameters = check.get("parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            if check_type == "record_exists":
                self._check_record_exists(source_records, parameters)
            elif check_type == "institution_completeness":
                self._check_institution_completeness(query_plan, source_records, parameters)
            elif check_type == "date_completeness":
                self._check_date_completeness(query_plan, source_records, parameters)
            elif check_type == "metric_completeness":
                self._check_metric_completeness(
                    query_plan,
                    source_records,
                    parameters,
                )
            elif check_type in {
                "denominator_nonzero",
                "unit_consistency",
                "unrounded_comparison",
                "tie_preservation",
            }:
                continue
            else:
                raise QueryExecutionError(f"确定性执行器不认识检查类型 {check_type}。")

    def _check_record_exists(
        self,
        records: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        filtered = records
        metric_ids = parameters.get("metric_ids")
        if isinstance(metric_ids, list) and metric_ids:
            filtered = [item for item in filtered if item.get("metric_id") in metric_ids]
        institution_id = parameters.get("institution_id")
        if isinstance(institution_id, str):
            filtered = [item for item in filtered if item.get("institution_id") == institution_id]
        institution_ids = parameters.get("institution_ids")
        if isinstance(institution_ids, list) and institution_ids:
            filtered = [item for item in filtered if item.get("institution_id") in institution_ids]
        data_date = parameters.get("date")
        if isinstance(data_date, str):
            filtered = [item for item in filtered if item.get("date") == data_date]
        if not filtered:
            raise QueryExecutionError("record_exists 检查失败。")

    def _check_institution_completeness(
        self,
        query_plan: dict[str, Any],
        records: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        explicit_expected = parameters.get("institution_ids")
        has_explicit_scope = (
            isinstance(explicit_expected, list)
            and bool(explicit_expected)
        )
        expected = explicit_expected
        if not has_explicit_scope:
            institutions = query_plan.get("institutions")
            population = (
                institutions.get("comparison_population")
                if isinstance(institutions, dict)
                else None
            )
            expected = (
                population.get("institution_ids")
                if isinstance(population, dict)
                else None
            )
        if not isinstance(expected, list) or not expected:
            expected = [f"ORG{index:03d}" for index in range(1, 14)]
        expected_set = {
            item for item in expected if isinstance(item, str)
        }

        filtered = list(records)
        metric_ids = parameters.get("metric_ids")
        if isinstance(metric_ids, list) and metric_ids:
            filtered = [
                item
                for item in filtered
                if item.get("metric_id") in metric_ids
            ]
        data_date = parameters.get("date")
        if isinstance(data_date, str):
            filtered = [
                item for item in filtered
                if item.get("date") == data_date
            ]
        dates = parameters.get("dates")
        if isinstance(dates, list) and dates:
            date_set = set(dates)
            filtered = [
                item for item in filtered
                if item.get("date") in date_set
            ]

        grouped: dict[tuple[Any, Any], set[Any]] = defaultdict(set)
        for record in filtered:
            grouped[(record.get("date"), record.get("metric_id"))].add(
                record.get("institution_id")
            )

        groups_to_check = list(grouped.values())
        if not has_explicit_scope:
            groups_to_check = [
                actual
                for actual in groups_to_check
                if len(
                    {
                        item for item in actual
                        if item is not None
                    }
                ) > 1
            ]

        if (
            not groups_to_check
            or any(
                not expected_set.issubset(actual)
                for actual in groups_to_check
            )
        ):
            raise QueryExecutionError(
                "institution_completeness 检查失败。"
            )

    def _check_date_completeness(
        self,
        query_plan: dict[str, Any],
        records: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        expected_dates: set[str] = set()
        if isinstance(parameters.get("start_date"), str) and isinstance(
            parameters.get("end_date"), str
        ):
            expected_dates = set(
                self._date_range(parameters["start_date"], parameters["end_date"])
            )
        else:
            time_plan = query_plan.get("time")
            if isinstance(time_plan, dict):
                dates = time_plan.get("dates")
                if isinstance(dates, list) and dates:
                    expected_dates = {str(item) for item in dates}
                elif isinstance(time_plan.get("start_date"), str) and isinstance(
                    time_plan.get("end_date"), str
                ):
                    expected_dates = set(
                        self._date_range(
                            time_plan["start_date"],
                            time_plan["end_date"],
                        )
                    )
        if not expected_dates:
            return
        grouped: dict[tuple[Any, Any], set[str]] = defaultdict(set)
        for record in records:
            grouped[(record.get("institution_id"), record.get("metric_id"))].add(
                str(record.get("date"))
            )
        if not grouped or any(not expected_dates.issubset(actual) for actual in grouped.values()):
            raise QueryExecutionError("date_completeness 检查失败。")

    @staticmethod
    def _check_metric_completeness(
        query_plan: dict[str, Any],
        records: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        expected = parameters.get("metric_ids")
        if not isinstance(expected, list) or not expected:
            raise QueryExecutionError(
                "metric_completeness 缺少 metric_ids。"
            )
        expected_set = set(expected)

        filtered = list(records)
        data_date = parameters.get("date")
        if isinstance(data_date, str):
            filtered = [
                item for item in filtered
                if item.get("date") == data_date
            ]
        dates = parameters.get("dates")
        if isinstance(dates, list) and dates:
            date_set = set(dates)
            filtered = [
                item for item in filtered
                if item.get("date") in date_set
            ]

        grouped: dict[Any, set[Any]] = defaultdict(set)
        for record in filtered:
            grouped[record.get("institution_id")].add(
                record.get("metric_id")
            )

        requested = parameters.get("institution_ids")
        if isinstance(requested, list) and requested:
            institutions = requested
        else:
            institution_plan = query_plan.get("institutions")
            targets = (
                institution_plan.get("targets")
                if isinstance(institution_plan, dict)
                else []
            )
            target_ids = [
                item.get("institution_id")
                for item in targets
                if isinstance(item, dict)
                and isinstance(item.get("institution_id"), str)
            ]
            institutions = (
                target_ids
                if target_ids
                else [key for key in grouped if key is not None]
            )

        if not institutions or any(
            not expected_set.issubset(
                grouped.get(institution_id, set())
            )
            for institution_id in institutions
        ):
            raise QueryExecutionError(
                "metric_completeness 检查失败。"
            )

    @staticmethod
    def _date_range(start_raw: str, end_raw: str) -> list[str]:
        try:
            start = date.fromisoformat(start_raw)
            end = date.fromisoformat(end_raw)
        except ValueError as exc:
            raise QueryExecutionError("完整性检查日期不合法。") from exc
        if start > end:
            raise QueryExecutionError("完整性检查起始日期晚于结束日期。")
        result: list[str] = []
        current = start
        while current <= end:
            result.append(current.isoformat())
            current += timedelta(days=1)
        return result

    def _output_records(
        self,
        value: ExecutionValue,
        output_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        records = self._records(value)
        target_ids = output_plan.get("_target_institution_ids")
        if not isinstance(target_ids, list) or not target_ids:
            return records
        target_set = {
            item for item in target_ids if isinstance(item, str)
        }
        if not target_set:
            return records
        if not any(
            record.get("institution_id") is not None
            for record in records
        ):
            return records
        return [
            record
            for record in records
            if record.get("institution_id") in target_set
        ]

    def _render(
        self,
        value: ExecutionValue,
        output_plan: dict[str, Any],
    ) -> tuple[list[str], list[list[JsonScalar]], str | None]:
        rounding = output_plan.get("rounding")
        digits = (
            rounding.get("digits", 2)
            if isinstance(rounding, dict)
            else 2
        )
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0:
            digits = 2

        if value.kind == "records":
            return self._render_records(
                self._output_records(value, output_plan),
                digits,
            )
        if value.kind == "scalar":
            if (
                value.data.get("operation")
                in {"difference", "absolute_difference"}
                and isinstance(value.data.get("left_record"), dict)
                and isinstance(value.data.get("right_record"), dict)
            ):
                labels = output_plan.get("result_fields")
                labels = labels if isinstance(labels, list) else []
                return self._render_comparison_composite(
                    [(0, value)],
                    labels,
                    digits,
                )
            numeric = self._json_number(value.data.get("value"), digits)
            unit = value.unit
            summary = f"计算结果为{numeric}{unit or ''}。"
            return ["value", "unit"], [[numeric, unit]], summary
        if value.kind == "date":
            resolved = value.data.get("date")
            return ["date"], [[resolved]], f"基期日期为{resolved}。"
        if value.kind == "count":
            count = int(value.data.get("count", 0))
            unit = output_plan.get("unit") or value.unit or "条"
            population_count = value.data.get("population_count")
            share_percent = value.data.get("share_percent")
            if (
                unit == "天"
                and isinstance(population_count, int)
                and population_count > 0
                and share_percent is not None
            ):
                rendered_share = self._json_number(share_percent, 2)
                return (
                    ["count", "unit", "population_count", "share_percent"],
                    [[count, unit, population_count, rendered_share]],
                    (
                        f"计数结果为{count}{unit}，"
                        f"占{population_count}{unit}的"
                        f"{self._display_number(share_percent, 2)}%。"
                    ),
                )
            return (
                ["count", "unit"],
                [[count, unit]],
                f"计数结果为{count}{unit}。",
            )
        if value.kind == "assessment":
            data = value.data
            metric_value = self._json_number(data.get("metric_value"), digits)
            threshold = self._json_number(data.get("threshold"), digits)
            gap = self._json_number(data.get("gap"), digits)
            is_met = bool(data.get("is_met"))
            unit = value.unit or ""
            summary = (
                f"指标值为{metric_value}{unit}，阈值为{threshold}{unit}，"
                f"{'符合' if is_met else '不符合'}要求，差距为{gap}个百分点。"
            )
            return (
                [
                    "metric_value",
                    "threshold",
                    "comparison_operator",
                    "is_met",
                    "gap",
                    "unit",
                ],
                [[
                    metric_value,
                    threshold,
                    data.get("comparison_operator"),
                    is_met,
                    gap,
                    unit,
                ]],
                summary,
            )
        if value.kind == "reconciliation":
            data = value.data
            row = [
                self._json_number(data.get("total_value"), digits),
                self._json_number(data.get("component_sum"), digits),
                bool(data.get("is_equal")),
                self._json_number(data.get("difference"), digits),
                value.unit,
            ]
            details = data.get("component_details")
            details = (
                details
                if isinstance(details, list)
                else []
            )
            valid_details = [
                item
                for item in details
                if isinstance(item, dict)
                and isinstance(
                    item.get("metric_name"),
                    str,
                )
                and item.get("value") is not None
            ]

            if valid_details:
                component_text = " + ".join(
                    f"{item['metric_name']}"
                    f"{self._display_number(item['value'], digits)}"
                    f"{item.get('unit') or value.unit or ''}"
                    for item in valid_details
                )
                total_label = (
                    data.get("total_label")
                    if isinstance(
                        data.get("total_label"),
                        str,
                    )
                    else "总量"
                )
                summary = (
                    f"{component_text} = "
                    f"{self._display_number(data.get('component_sum'), digits)}"
                    f"{value.unit or ''}；"
                    f"{total_label}"
                    f"{self._display_number(data.get('total_value'), digits)}"
                    f"{value.unit or ''}；"
                    f"总量与分项合计"
                    f"{'一致' if row[2] else '不一致'}，"
                    f"差额为{row[3]}{value.unit or ''}。"
                )
            else:
                summary = (
                    f"总量与分项合计"
                    f"{'一致' if row[2] else '不一致'}，"
                    f"差额为{row[3]}{value.unit or ''}。"
                )
            return (
                ["total_value", "component_sum", "is_equal", "difference", "unit"],
                [row],
                summary,
            )
        if value.kind == "trend":
            series = value.data.get("series", [])
            trends = value.data.get("trends", [])
            trend_map = {
                (item.get("institution_id"), item.get("metric_id")): item.get("trend")
                for item in trends
            }
            enriched = []
            for item in series:
                current = dict(item)
                current["trend"] = trend_map.get(
                    (item.get("institution_id"), item.get("metric_id"))
                )
                enriched.append(current)
            columns, rows, _ = self._render_records(enriched, digits)
            labels = [str(item.get("trend")) for item in trends]
            summary = "趋势判断：" + "；".join(labels) + "。"
            return columns, rows, summary
        if value.kind == "composite":
            return self._render_composite(value, output_plan, digits)
        raise QueryExecutionError(f"无法渲染执行结果类型 {value.kind}。")

    def _render_composite(
        self,
        value: ExecutionValue,
        output_plan: dict[str, Any],
        digits: int,
    ) -> tuple[list[str], list[list[JsonScalar]], str | None]:
        items: list[ExecutionValue] = value.data.get("items", [])
        labels = output_plan.get("result_fields")
        labels = labels if isinstance(labels, list) else []
        if len(labels) != len(items):
            labels = []

        comparison_items = [
            (index, item)
            for index, item in enumerate(items)
            if item.kind == "scalar"
            and item.data.get("operation") in {
                "difference",
                "absolute_difference",
            }
            and isinstance(item.data.get("left_record"), dict)
            and isinstance(item.data.get("right_record"), dict)
        ]
        if comparison_items and len(comparison_items) == len(items):
            return self._render_comparison_composite(
                comparison_items,
                labels,
                digits,
            )

        trend_series = [
            item.data.get("series")
            for item in items
            if item.kind == "trend"
            and isinstance(item.data.get("series"), list)
        ]
        effective_items: list[tuple[int, ExecutionValue]] = []
        for index, item in enumerate(items):
            if item.kind == "records" and any(
                item.data == series for series in trend_series
            ):
                continue
            effective_items.append((index, item))

        has_nonempty_record_output = any(
            item.kind == "records"
            and bool(self._output_records(item, output_plan))
            for _, item in effective_items
        )
        if has_nonempty_record_output:
            effective_items = [
                (index, item)
                for index, item in effective_items
                if not (
                    item.kind == "records"
                    and not self._output_records(
                        item,
                        output_plan,
                    )
                )
            ]

        record_like_items = [
            (index, item)
            for index, item in effective_items
            if item.kind in {"records", "trend"}
        ]
        count_items = [
            (index, item)
            for index, item in effective_items
            if item.kind == "count"
        ]

        if len(record_like_items) == 1 and all(
            item.kind in {"records", "trend", "count"}
            for _, item in effective_items
        ):
            _, record_item = record_like_items[0]
            if record_item.kind == "trend":
                columns, rows, record_summary = self._render(
                    record_item,
                    output_plan,
                )
            else:
                columns, rows, record_summary = self._render_records(
                    self._output_records(record_item, output_plan),
                    digits,
                )
            if count_items:
                _, count_item = count_items[0]
                count = int(count_item.data.get("count", 0))
                unit = count_item.unit or "条"
                return (
                    columns,
                    rows,
                    f"满足条件的数量为{count}{unit}。{record_summary or ''}",
                )
            return columns, rows, record_summary

        scalar_items = [
            (index, item)
            for index, item in effective_items
            if item.kind == "scalar"
        ]

        simple_numeric_items = bool(effective_items) and all(
            item.kind == "scalar"
            or (
                item.kind == "records"
                and len(self._records(item)) == 1
                and self._records(item)[0].get("rank") is None
                and self._records(item)[0].get("result_type") is None
                and self._records(item)[0].get("trend") is None
            )
            for _, item in effective_items
        )
        if simple_numeric_items and len(effective_items) >= 2:
            rows: list[list[JsonScalar]] = []
            summary_parts: list[str] = []
            for index, item in effective_items:
                provided_label = (
                    str(labels[index])
                    if index < len(labels)
                    else None
                )
                raw_label = self._composite_label(
                    item,
                    provided_label,
                    index,
                )
                if item.kind == "records":
                    record = self._records(item)[0]
                    metric_name = str(
                        record.get("metric_name")
                        or raw_label
                    )
                    numeric = self._decimal(
                        record.get("value"),
                        "composite record",
                    )
                    unit = str(record.get("unit") or item.unit or "")
                    friendly_label = self._friendly_result_label(
                        raw_label,
                        metric_name,
                    )
                else:
                    metric_name = raw_label
                    numeric = self._decimal(
                        item.data.get("value"),
                        "composite scalar",
                    )
                    unit = str(item.unit or "")
                    friendly_label = self._friendly_result_label(
                        raw_label,
                        None,
                    )

                rows.append(
                    [
                        raw_label,
                        friendly_label,
                        self._json_number(numeric, digits),
                        unit,
                    ]
                )
                if raw_label in {"mom_change", "yoy_change"}:
                    if numeric > 0:
                        direction = "增长"
                    elif numeric < 0:
                        direction = "下降"
                    else:
                        direction = "保持不变"
                    summary_parts.append(
                        f"{friendly_label}{direction}"
                        + (
                            ""
                            if numeric == 0
                            else self._display_number(
                                abs(numeric),
                                digits,
                            )
                            + unit
                        )
                    )
                else:
                    summary_parts.append(
                        f"{friendly_label}为"
                        f"{self._display_number(numeric, digits)}"
                        f"{unit}"
                    )
            return (
                ["result", "label", "value", "unit"],
                rows,
                "；".join(summary_parts) + "。",
            )

        if (
            len(record_like_items) == 1
            and scalar_items
            and all(
                item.kind in {"records", "scalar"}
                for _, item in effective_items
            )
        ):
            record_index, record_item = record_like_items[0]
            records = self._output_records(
                record_item,
                output_plan,
            )
            if len(records) == 1:
                rows: list[list[JsonScalar]] = []
                summary_parts: list[str] = []
                for index, item in effective_items:
                    provided_label = (
                        str(labels[index])
                        if index < len(labels)
                        else None
                    )
                    label = self._composite_label(
                        item,
                        provided_label,
                        index,
                    )
                    friendly_label = {
                        "current_value": "当前值",
                        "mom_change": "环比",
                        "yoy_change": "同比",
                    }.get(label, label)
                    if item.kind == "records":
                        # `records` has already been reduced to the requested
                        # institution by _output_records above.  Reading the
                        # original item here would silently pick the first
                        # province-wide ranking row instead of the target.
                        record = records[0]
                        value_number = self._json_number(
                            record.get("value"),
                            digits,
                        )
                        unit = str(record.get("unit") or item.unit or "")
                        rows.append([label, value_number, unit])
                        summary_parts.append(
                            f"{friendly_label}为"
                            f"{self._display_number(record.get('value'), digits)}"
                            f"{unit}"
                        )
                    else:
                        numeric = self._decimal(
                            item.data.get("value"),
                            "composite scalar",
                        )
                        value_number = self._json_number(numeric, digits)
                        unit = item.unit or ""
                        rows.append([label, value_number, unit])
                        if label in {"mom_change", "yoy_change"}:
                            if numeric > 0:
                                direction = "增长"
                            elif numeric < 0:
                                direction = "下降"
                            else:
                                direction = "保持不变"
                            summary_parts.append(
                                f"{friendly_label}{direction}"
                                + (
                                    ""
                                    if numeric == 0
                                    else self._display_number(
                                        abs(numeric),
                                        digits,
                                    )
                                    + unit
                                )
                            )
                        else:
                            summary_parts.append(
                                f"{friendly_label}为"
                                f"{self._display_number(numeric, digits)}"
                                f"{unit}"
                            )
                return (
                    ["result", "value", "unit"],
                    rows,
                    "；".join(summary_parts) + "。",
                )

        if record_like_items:
            rendered_groups: list[
                tuple[str, list[str], list[list[JsonScalar]], str | None]
            ] = []
            union_columns: list[str] = []
            summary_parts: list[str] = []

            for index, item in record_like_items:
                provided_label = (
                    str(labels[index])
                    if index < len(labels)
                    else None
                )
                label = self._composite_label(
                    item,
                    provided_label,
                    index,
                )
                if item.kind == "trend":
                    columns, rows, summary = self._render(
                        item,
                        output_plan,
                    )
                else:
                    columns, rows, summary = self._render_records(
                        self._output_records(item, output_plan),
                        digits,
                    )
                for column in columns:
                    if (
                        column != "result"
                        and column not in union_columns
                    ):
                        union_columns.append(column)
                rendered_groups.append(
                    (label, columns, rows, summary)
                )
                if summary:
                    cleaned_summary = summary.rstrip("。；")
                    if cleaned_summary.startswith(label):
                        summary_parts.append(cleaned_summary)
                    else:
                        summary_parts.append(
                            f"{label}：{cleaned_summary}"
                        )

            if scalar_items:
                for column in (
                    "metric_id",
                    "metric_name",
                    "metric_value",
                    "unit",
                ):
                    if column not in union_columns:
                        union_columns.append(column)

            composite_rows: list[list[JsonScalar]] = []
            for label, columns, rows, _ in rendered_groups:
                for row in rows:
                    row_map = dict(zip(columns, row))
                    composite_rows.append(
                        [
                            label,
                            *[
                                row_map.get(column)
                                for column in union_columns
                            ],
                        ]
                    )

            for index, item in scalar_items:
                provided_label = (
                    str(labels[index])
                    if index < len(labels)
                    else None
                )
                label = self._composite_label(
                    item,
                    provided_label,
                    index,
                )
                numeric = self._decimal(
                    item.data.get("value"),
                    "composite scalar",
                )
                metric_name = (
                    item.metadata.get("metric_name")
                    if isinstance(
                        item.metadata.get("metric_name"),
                        str,
                    )
                    else label
                )
                row_map = {
                    "metric_id": item.metadata.get("metric_id"),
                    "metric_name": metric_name,
                    "metric_value": self._json_number(
                        numeric,
                        digits,
                    ),
                    "unit": item.unit,
                }
                composite_rows.append(
                    [
                        label,
                        *[
                            row_map.get(column)
                            for column in union_columns
                        ],
                    ]
                )
                if item.data.get("operation") in {
                    "difference",
                    "absolute_difference",
                    "percentage_point_change",
                }:
                    direction = self._change_direction(numeric)
                    summary_parts.append(
                        f"{label}{direction}"
                        + (
                            ""
                            if numeric == 0
                            else self._display_number(
                                abs(numeric),
                                digits,
                            )
                            + str(item.unit or "")
                        )
                    )
                else:
                    summary_parts.append(
                        f"{label}为"
                        f"{self._display_number(numeric, digits)}"
                        f"{item.unit or ''}"
                    )

            for index, item in count_items:
                provided_label = (
                    str(labels[index])
                    if index < len(labels)
                    else None
                )
                label = self._composite_label(
                    item,
                    provided_label,
                    index,
                )
                count = int(item.data.get("count", 0))
                unit = item.unit or "条"
                summary_parts.append(f"{label}为{count}{unit}")

            summary = (
                "；".join(summary_parts) + "。"
                if summary_parts
                else None
            )
            return (
                ["result", *union_columns],
                composite_rows,
                summary,
            )

        rows: list[list[JsonScalar]] = []
        summary_parts: list[str] = []
        for index, item in effective_items:
            provided_label = (
                str(labels[index])
                if index < len(labels)
                else None
            )
            label = self._composite_label(
                item,
                provided_label,
                index,
            )
            if item.kind == "scalar":
                rendered = self._json_number(
                    item.data.get("value"),
                    digits,
                )
                rows.append([label, rendered, item.unit])
                summary_parts.append(
                    f"{label}为{self._display_number(item.data.get('value'), digits)}"
                    f"{item.unit or ''}"
                )
            elif item.kind == "date":
                rendered = item.data.get("date")
                rows.append([label, rendered, None])
                summary_parts.append(f"{label}为{rendered}")
            elif item.kind == "count":
                rendered = int(item.data.get("count", 0))
                unit = item.unit or "条"
                rows.append([label, rendered, unit])
                summary_parts.append(f"{label}为{rendered}{unit}")
            else:
                rendered = json.dumps(
                    self._jsonable(item.data, digits),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                rows.append([label, rendered, item.unit])
                summary_parts.append(f"{label}已生成")
        return (
            ["result", "value", "unit"],
            rows,
            "；".join(summary_parts) + "。",
        )

    def _render_comparison_composite(
        self,
        comparison_items: list[tuple[int, ExecutionValue]],
        labels: list[Any],
        digits: int,
    ) -> tuple[list[str], list[list[JsonScalar]], str | None]:
        columns = [
            "result",
            "metric_name",
            "base_date",
            "base_value",
            "current_date",
            "current_value",
            "change",
            "direction",
            "unit",
        ]
        rows: list[list[JsonScalar]] = []
        summaries: list[str] = []

        for index, item in comparison_items:
            left_record = item.data["left_record"]
            right_record = item.data["right_record"]
            current_value = item.data.get("left_value")
            base_value = item.data.get("right_value")
            change = item.data.get("value")
            unit = item.unit or left_record.get("unit") or right_record.get("unit")
            metric_name = (
                left_record.get("metric_name")
                or right_record.get("metric_name")
                or (
                    str(labels[index])
                    if index < len(labels)
                    else f"result_{index + 1}"
                )
            )
            direction = self._change_direction(change)
            label = (
                str(labels[index])
                if index < len(labels)
                else str(metric_name)
            )
            rows.append(
                [
                    label,
                    metric_name,
                    right_record.get("date"),
                    self._json_number(base_value, digits),
                    left_record.get("date"),
                    self._json_number(current_value, digits),
                    self._json_number(change, digits),
                    direction,
                    unit,
                ]
            )
            summaries.append(
                f"{metric_name}："
                f"{self._display_number(base_value, digits)}{unit or ''}"
                f"→{self._display_number(current_value, digits)}{unit or ''}，"
                f"{direction}"
                + (
                    ""
                    if direction == "保持不变"
                    else f"{self._display_number(abs(self._decimal(change, 'change')), digits)}"
                    f"{unit or ''}"
                )
            )

        return columns, rows, "；".join(summaries) + "。"

    @staticmethod
    def _change_direction(value: object) -> str:
        numeric = Decimal(str(value))
        if numeric > 0:
            return "增加"
        if numeric < 0:
            return "减少"
        return "保持不变"

    @staticmethod
    def _friendly_result_label(
        raw_label: str,
        metric_name: str | None,
    ) -> str:
        mapping = {
            "current_value": "当前值",
            "mom_change": "环比",
            "yoy_change": "同比",
            "corp_customers": "对公客户数",
            "corporate_customers": "对公客户数",
            "personal_customers": "个人客户数",
            "total_customers": "合计客户数",
            "corporate_loan_ratio": "对公贷款占比",
            "duigong_loan_ratio": "对公贷款占比",
            "personal_loan_ratio": "个人贷款占比",
            "geren_loan_ratio": "个人贷款占比",
            "npl_rate": "不良贷款率",
            "provision_coverage": "拨备覆盖率",
            "net_profit_change": "净利润较年初变化",
            "cost_income_ratio_change": "成本收入比较年初变化",
            "net_interest_income_change": "净利息收入较年初变化",
            "intermediate_income_change": "中间业务收入较年初变化",
            "net_interest_ratio_current": "净利息收入占营业收入比重",
            "intermediate_income_ratio_current": "中间业务收入占营业收入比重",
            "intermediate_ratio_current": "中间业务收入占营业收入比重",
            "ldr": "存贷比",
            "ldr_value": "存贷比",
        }
        if raw_label in mapping:
            return mapping[raw_label]
        if metric_name:
            if "change" in raw_label:
                return f"{metric_name}较基期变化"
            return metric_name
        return raw_label

    @staticmethod
    def _composite_label(
        item: ExecutionValue,
        provided_label: str | None,
        index: int,
    ) -> str:
        generic_labels = {
            None,
            "",
            "date",
            "value",
            "trend",
            "institution",
            "metric_value",
            "result",
        }
        result_type = item.metadata.get("result_type")
        if result_type is None and item.kind == "records" and item.data:
            result_type = item.data[0].get("result_type")
        if result_type == "maximum":
            return "最高值"
        if result_type == "minimum":
            return "最低值"
        if item.kind == "trend":
            return "时间序列与趋势"
        if item.kind == "count":
            return "数量"

        output_ref = item.metadata.get("output_ref")
        candidate = (
            str(provided_label)
            if provided_label not in generic_labels
            else str(output_ref)
            if isinstance(output_ref, str) and output_ref
            else ""
        )

        metric_name = (
            item.metadata.get("metric_name")
            if isinstance(item.metadata.get("metric_name"), str)
            else None
        )
        if metric_name is None and item.kind == "records":
            names = {
                str(record.get("metric_name"))
                for record in item.data
                if isinstance(record, dict)
                and isinstance(record.get("metric_name"), str)
            }
            if len(names) == 1:
                metric_name = next(iter(names))

        if metric_name:
            lowered = candidate.lower()
            if candidate in {
                "current_value",
                "mom_change",
                "yoy_change",
            }:
                return candidate
            if any(token in lowered for token in ("top3", "best")):
                return f"{metric_name}表现较好"
            if any(token in lowered for token in ("bottom4", "worst")):
                return f"{metric_name}表现较差"
            if "rank" in lowered or "perf" in lowered:
                return f"{metric_name}排名"
            if "change" in lowered:
                return f"{metric_name}较基期变化"
            return metric_name

        mapping = {
            "net_profit_change": "净利润较年初变化",
            "cost_income_ratio_change": "成本收入比较年初变化",
            "net_interest_income_change": "净利息收入较年初变化",
            "intermediate_income_change": "中间业务收入较年初变化",
            "ldr": "存贷比",
            "ldr_value": "存贷比",
        }
        if candidate in mapping:
            return mapping[candidate]
        if candidate:
            return candidate
        if item.kind == "records":
            return "明细"
        return f"结果{index + 1}"

    @staticmethod
    def _display_number(value: object, digits: int) -> str:
        numeric = Decimal(str(value))
        quantizer = Decimal(1).scaleb(-digits)
        return format(
            numeric.quantize(quantizer, rounding=ROUND_HALF_UP),
            f".{digits}f",
        )

    def _render_records(
        self,
        records: list[dict[str, Any]],
        digits: int,
    ) -> tuple[list[str], list[list[JsonScalar]], str | None]:
        fields = [
            ("result_type", "result_type"),
            ("institution_id", "institution_id"),
            ("institution_name", "institution_name"),
            ("date", "date"),
            ("metric_id", "metric_id"),
            ("metric_name", "metric_name"),
            ("value", "metric_value"),
            ("unit", "unit"),
            ("rank", "rank"),
            ("trend", "trend"),
        ]
        selected = [
            (source, target)
            for source, target in fields
            if any(record.get(source) is not None for record in records)
        ]
        columns = [target for _, target in selected]
        rows: list[list[JsonScalar]] = []
        for record in records:
            row: list[JsonScalar] = []
            for source, _ in selected:
                current = record.get(source)
                if source == "value":
                    current = self._json_number(current, digits)
                elif isinstance(current, Decimal):
                    current = self._json_number(current, digits)
                row.append(current)
            rows.append(row)

        if not records:
            return columns or ["result"], rows, "没有符合条件的记录。"
        summary_parts: list[str] = []
        for record in records[:20]:
            name = record.get("institution_name") or record.get("institution_id") or ""
            data_date = record.get("date") or ""
            display_value = self._display_number(
                record.get("value"),
                digits,
            )
            unit = record.get("unit") or ""
            rank = f"，第{record['rank']}名" if record.get("rank") is not None else ""
            prefix = "".join(part for part in (str(name), str(data_date)) if part)
            result_type = record.get("result_type")
            role = (
                "最高值"
                if result_type == "maximum"
                else "最低值"
                if result_type == "minimum"
                else ""
            )
            role_prefix = f"{role}：" if role else ""
            summary_parts.append(
                f"{role_prefix}{prefix}：{display_value}{unit}{rank}"
            )
        summary = "；".join(summary_parts) + "。"
        if len(records) > 20:
            summary += f"共{len(records)}条记录，摘要仅展示前20条。"
        return columns, rows, summary

    @staticmethod
    def _records(value: ExecutionValue) -> list[dict[str, Any]]:
        if value.kind != "records" or not isinstance(value.data, list):
            raise QueryExecutionError("算子需要记录集合输入。")
        if not all(isinstance(item, dict) for item in value.data):
            raise QueryExecutionError("记录集合内部格式错误。")
        return value.data

    def _single_numeric(self, value: ExecutionValue) -> tuple[Decimal, str | None]:
        if value.kind == "scalar" and isinstance(value.data, dict):
            return self._decimal(value.data.get("value"), "numeric input"), value.unit
        if value.kind == "records":
            records = self._records(value)
            if len(records) != 1:
                raise QueryExecutionError("该算子要求唯一数值，但输入包含多条记录。")
            return self._decimal(records[0].get("value"), "numeric input"), records[0].get("unit")
        raise QueryExecutionError("该算子要求数值输入。")

    @staticmethod
    def _decimal(value: Any, operation: str) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise QueryExecutionError(f"{operation} 输入不是数值。")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise QueryExecutionError(f"{operation} 输入不是数值。") from exc

    @staticmethod
    def _require_input_count(
        inputs: list[ExecutionValue],
        expected: int,
        operator_id: str,
    ) -> None:
        if len(inputs) != expected:
            raise QueryExecutionError(f"{operator_id} 必须接收{expected}个输入。")

    @staticmethod
    def _require_same_unit(units: Iterable[Any], operation: str) -> None:
        normalized = {str(item) for item in units if item not in {None, ""}}
        if len(normalized) > 1:
            raise QueryExecutionError(f"{operation} 输入单位不一致。")

    @staticmethod
    def _record_count(value: ExecutionValue) -> int | None:
        if value.kind == "records" and isinstance(value.data, list):
            return len(value.data)
        if value.kind == "trend" and isinstance(value.data, dict):
            series = value.data.get("series")
            return len(series) if isinstance(series, list) else None
        if value.kind == "count" and isinstance(value.data, dict):
            count = value.data.get("count")
            return int(count) if isinstance(count, int) else None
        return None

    @staticmethod
    def _json_number(value: Any, digits: int) -> int | float | None:
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        quantizer = Decimal(1).scaleb(-digits)
        rounded = decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP)
        if digits == 0:
            return int(rounded)
        return float(rounded)

    def _jsonable(self, value: Any, digits: int) -> Any:
        if isinstance(value, Decimal):
            return self._json_number(value, digits)
        if isinstance(value, dict):
            return {key: self._jsonable(item, digits) for key, item in value.items()}
        if isinstance(value, list):
            return [self._jsonable(item, digits) for item in value]
        if isinstance(value, ExecutionValue):
            return {
                "kind": value.kind,
                "data": self._jsonable(value.data, digits),
                "unit": value.unit,
            }
        return value
