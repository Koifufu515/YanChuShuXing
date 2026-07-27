from __future__ import annotations

import calendar
import json
import operator
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import perf_counter
from typing import Any, Callable, Iterable

from app.application.errors import QueryExecutionError
from app.application.models import JsonScalar, QueryPlanExecutionResult
from app.ports.database_executor import DatabaseExecutor


@dataclass
class ExecutionValue:
    kind: str
    data: Any
    unit: str | None = None
    operator_id: str | None = None


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
        columns, rows, summary = self._render(
            final_value,
            query_plan.get("output") if isinstance(query_plan.get("output"), dict) else {},
        )
        return QueryPlanExecutionResult(
            columns=columns,
            rows=rows,
            summary=summary,
            warnings=[],
            execution_trace=trace,
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
        for value in inputs[1:]:
            numeric, unit = self._single_numeric(value)
            components.append(numeric)
            component_units.append(unit)
        self._require_same_unit([total_unit, *component_units], "OP005")
        component_sum = sum(components, Decimal(0))
        difference = total - component_sum
        return ExecutionValue(
            kind="reconciliation",
            data={
                "total_value": total,
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
        return self._binary_transform(
            inputs[0],
            inputs[1],
            self._ratio,
            "ratio",
            result_unit="%",
            require_same_unit=False,
        )

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
        self._require_input_count(inputs, 1, "OP009")
        records = self._records(inputs[0])
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
        return ExecutionValue(kind="records", data=output, unit=inputs[0].unit)

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
        self._require_input_count(inputs, 1, "OP011")
        order = parameters.get("order")
        if order not in {"ascending", "descending"}:
            raise QueryExecutionError("OP011.order 不合法。")
        return self._rank_records(
            self._records(inputs[0]),
            reverse=order == "descending",
        )

    def _op_performance_rank(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP012")
        direction = parameters.get("performance_direction")
        if direction not in {"higher_is_better", "lower_is_better"}:
            raise QueryExecutionError("OP012.performance_direction 不合法。")
        return self._rank_records(
            self._records(inputs[0]),
            reverse=direction == "higher_is_better",
        )

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
                boundary_index = len(group) - n
                boundary = self._decimal(group[boundary_index].get("value"), "OP013")
                selected = [
                    item
                    for item in group
                    if item in group[boundary_index:]
                    or self._decimal(item.get("value"), "OP013") == boundary
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
        selected = [
            dict(item)
            for item in records
            if self._decimal(item.get("value"), "OP014") == extreme
        ]
        return ExecutionValue(kind="records", data=selected, unit=inputs[0].unit)

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
        return ExecutionValue(kind="records", data=selected, unit=inputs[0].unit)

    def _op_count(
        self,
        inputs: list[ExecutionValue],
        parameters: dict[str, Any],
    ) -> ExecutionValue:
        self._require_input_count(inputs, 1, "OP017")
        value = inputs[0]
        if value.kind == "records":
            count = len(value.data)
        elif value.kind == "composite":
            count = len(value.data.get("items", []))
        elif isinstance(value.data, list):
            count = len(value.data)
        else:
            count = 1
        return ExecutionValue(kind="count", data={"count": count}, unit=None)

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
    ) -> ExecutionValue:
        if left.kind == "records" and right.kind == "records":
            left_records = self._records(left)
            right_records = self._records(right)
            if len(left_records) == len(right_records) == 1:
                left_value = self._decimal(left_records[0].get("value"), result_name)
                right_value = self._decimal(right_records[0].get("value"), result_name)
                if require_same_unit:
                    self._require_same_unit(
                        [left_records[0].get("unit"), right_records[0].get("unit")],
                        result_name,
                    )
                return ExecutionValue(
                    kind="scalar",
                    data={"value": function(left_value, right_value)},
                    unit=result_unit or left_records[0].get("unit"),
                )
            return self._aligned_record_transform(
                left_records,
                right_records,
                function,
                result_unit=result_unit,
                require_same_unit=require_same_unit,
            )

        left_value, left_unit = self._single_numeric(left)
        right_value, right_unit = self._single_numeric(right)
        if require_same_unit:
            self._require_same_unit([left_unit, right_unit], result_name)
        return ExecutionValue(
            kind="scalar",
            data={"value": function(left_value, right_value)},
            unit=result_unit or left_unit,
        )

    def _aligned_record_transform(
        self,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        function: Callable[[Decimal, Decimal], Decimal],
        result_unit: str | None,
        require_same_unit: bool,
    ) -> ExecutionValue:
        def candidate_key(record: dict[str, Any], include_institution: bool) -> tuple[Any, ...]:
            base = (record.get("date"), record.get("metric_id"))
            return (
                (record.get("institution_id"), *base)
                if include_institution
                else base
            )

        for include_institution in (False, True):
            left_keys = [candidate_key(item, include_institution) for item in left_records]
            right_keys = [candidate_key(item, include_institution) for item in right_records]
            if len(set(left_keys)) != len(left_keys) or len(set(right_keys)) != len(right_keys):
                continue
            if set(left_keys) != set(right_keys):
                continue
            right_map = dict(zip(right_keys, right_records))
            output: list[dict[str, Any]] = []
            for key, left_record in zip(left_keys, left_records):
                right_record = right_map[key]
                if require_same_unit:
                    self._require_same_unit(
                        [left_record.get("unit"), right_record.get("unit")],
                        "aligned operation",
                    )
                current = dict(left_record)
                current["value"] = function(
                    self._decimal(left_record.get("value"), "aligned operation"),
                    self._decimal(right_record.get("value"), "aligned operation"),
                )
                if result_unit is not None:
                    current["unit"] = result_unit
                output.append(current)
            return ExecutionValue(
                kind="records",
                data=output,
                unit=result_unit or left_records[0].get("unit"),
            )
        raise QueryExecutionError("两个记录集合无法按机构、日期和指标对齐。")

    @staticmethod
    def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == 0:
            raise QueryExecutionError("比例计算分母为0。")
        return numerator / denominator * Decimal(100)

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
                self._check_metric_completeness(source_records, parameters)
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
        expected = parameters.get("institution_ids")
        if not isinstance(expected, list) or not expected:
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
        expected_set = set(expected)
        grouped: dict[tuple[Any, Any], set[Any]] = defaultdict(set)
        for record in records:
            grouped[(record.get("date"), record.get("metric_id"))].add(
                record.get("institution_id")
            )
        if not grouped or any(not expected_set.issubset(actual) for actual in grouped.values()):
            raise QueryExecutionError("institution_completeness 检查失败。")

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
        records: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        expected = parameters.get("metric_ids")
        if not isinstance(expected, list) or not expected:
            raise QueryExecutionError("metric_completeness 缺少 metric_ids。")
        expected_set = set(expected)
        grouped: dict[tuple[Any, Any], set[Any]] = defaultdict(set)
        for record in records:
            grouped[(record.get("institution_id"), record.get("date"))].add(
                record.get("metric_id")
            )
        if not grouped or any(not expected_set.issubset(actual) for actual in grouped.values()):
            raise QueryExecutionError("metric_completeness 检查失败。")

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
            return self._render_records(self._records(value), digits)
        if value.kind == "scalar":
            numeric = self._json_number(value.data.get("value"), digits)
            unit = value.unit
            summary = f"计算结果为{numeric}{unit or ''}。"
            return ["value", "unit"], [[numeric, unit]], summary
        if value.kind == "date":
            resolved = value.data.get("date")
            return ["date"], [[resolved]], f"基期日期为{resolved}。"
        if value.kind == "count":
            count = int(value.data.get("count", 0))
            return ["count"], [[count]], f"共{count}条结果。"
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
            summary = (
                f"总量与分项合计{'一致' if row[2] else '不一致'}，"
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
        record_item = next((item for item in items if item.kind == "records"), None)
        count_item = next((item for item in items if item.kind == "count"), None)
        if record_item is not None:
            columns, rows, record_summary = self._render_records(
                self._records(record_item), digits
            )
            if count_item is not None:
                count = int(count_item.data.get("count", 0))
                return columns, rows, f"共{count}条结果。{record_summary or ''}"
            return columns, rows, record_summary

        labels = output_plan.get("result_fields")
        labels = labels if isinstance(labels, list) else []
        rows: list[list[JsonScalar]] = []
        summary_parts: list[str] = []
        for index, item in enumerate(items):
            label = str(labels[index]) if index < len(labels) else f"result_{index + 1}"
            if item.kind == "scalar":
                rendered = self._json_number(item.data.get("value"), digits)
                rows.append([label, rendered, item.unit])
                summary_parts.append(f"{label}为{rendered}{item.unit or ''}")
            elif item.kind == "date":
                rendered = item.data.get("date")
                rows.append([label, rendered, None])
                summary_parts.append(f"{label}为{rendered}")
            elif item.kind == "count":
                rendered = int(item.data.get("count", 0))
                rows.append([label, rendered, None])
                summary_parts.append(f"{label}为{rendered}")
            else:
                rendered = json.dumps(
                    self._jsonable(item.data, digits),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                rows.append([label, rendered, item.unit])
                summary_parts.append(f"{label}已生成")
        return ["result", "value", "unit"], rows, "；".join(summary_parts) + "。"

    def _render_records(
        self,
        records: list[dict[str, Any]],
        digits: int,
    ) -> tuple[list[str], list[list[JsonScalar]], str | None]:
        fields = [
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
            value = self._json_number(record.get("value"), digits)
            unit = record.get("unit") or ""
            rank = f"，第{record['rank']}名" if record.get("rank") is not None else ""
            prefix = "".join(part for part in (str(name), str(data_date)) if part)
            summary_parts.append(f"{prefix}：{value}{unit}{rank}")
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
