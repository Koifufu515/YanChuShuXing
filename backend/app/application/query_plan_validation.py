from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any


ValidationError = dict[str, str]


def parse_iso_date(
    value: object,
    field_path: str,
    errors: list[ValidationError],
) -> date | None:
    if not isinstance(value, str):
        errors.append(
            {
                "path": field_path,
                "message": f"日期必须是字符串YYYY-MM-DD，实际为：{value!r}",
            }
        )
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(
            {
                "path": field_path,
                "message": f"日期必须是合法的ISO格式YYYY-MM-DD，实际为：{value!r}",
            }
        )
        return None


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def resolve_base_date(base_type: str, reference: date) -> date | None:
    if base_type == "previous_month_end":
        year = reference.year
        month = reference.month - 1
        if month == 0:
            year -= 1
            month = 12
        return month_end(year, month)

    if base_type == "previous_quarter_end":
        quarter = (reference.month - 1) // 3 + 1
        if quarter == 1:
            return date(reference.year - 1, 12, 31)
        return month_end(reference.year, (quarter - 1) * 3)

    if base_type == "previous_year_same_period":
        previous_year = reference.year - 1
        if reference == month_end(reference.year, reference.month):
            return month_end(previous_year, reference.month)
        try:
            return reference.replace(year=previous_year)
        except ValueError:
            return date(previous_year, 2, 28)

    if base_type in {"previous_year_end", "year_begin_base"}:
        return date(reference.year - 1, 12, 31)

    return None


def collect_plan_dates(
    plan: dict[str, Any],
    errors: list[ValidationError],
) -> list[tuple[str, date]]:
    """收集time、operation parameters及OP021推导出的全部必要日期。"""
    collected: list[tuple[str, date]] = []

    def add_date(path: str, raw_value: object) -> None:
        parsed = parse_iso_date(raw_value, path, errors)
        if parsed is not None:
            collected.append((path, parsed))

    time_plan = plan.get("time")
    if isinstance(time_plan, dict):
        dates = time_plan.get("dates")
        if isinstance(dates, list):
            for index, value in enumerate(dates):
                add_date(f"time.dates.{index}", value)

        for field in ("start_date", "end_date"):
            value = time_plan.get(field)
            if value is not None:
                add_date(f"time.{field}", value)

        periods = time_plan.get("comparison_periods")
        if isinstance(periods, list):
            for index, period in enumerate(periods):
                if not isinstance(period, dict):
                    continue
                for field in ("date", "start_date", "end_date"):
                    value = period.get(field)
                    if value is not None:
                        add_date(
                            f"time.comparison_periods.{index}.{field}",
                            value,
                        )

    operations = plan.get("operations")
    if isinstance(operations, list):
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                continue
            parameters = operation.get("parameters")
            if not isinstance(parameters, dict):
                continue

            for field in (
                "date",
                "start_date",
                "end_date",
                "reference_date",
            ):
                value = parameters.get(field)
                if value is not None:
                    add_date(
                        f"operations.{index}.parameters.{field}",
                        value,
                    )

            values = parameters.get("dates")
            if isinstance(values, list):
                for date_index, value in enumerate(values):
                    add_date(
                        f"operations.{index}.parameters.dates.{date_index}",
                        value,
                    )

            if operation.get("operator_id") == "OP021":
                base_type = parameters.get("type")
                reference_raw = parameters.get("reference_date")
                reference = None
                if isinstance(reference_raw, str):
                    try:
                        reference = date.fromisoformat(reference_raw)
                    except ValueError:
                        reference = None
                if isinstance(base_type, str) and reference is not None:
                    expected = resolve_base_date(base_type, reference)
                    if expected is not None:
                        collected.append(
                            (
                                f"operations.{index}.derived_base_date",
                                expected,
                            )
                        )

    return collected


def has_check(plan: dict[str, Any], check_type: str) -> bool:
    checks = plan.get("checks")
    return isinstance(checks, list) and any(
        isinstance(item, dict) and item.get("type") == check_type
        for item in checks
    )


def validate_business_rules(
    plan: dict[str, Any],
    context: dict[str, Any],
    question: str,
) -> list[ValidationError]:
    """校验JSON Schema难以表达的日期、算子语义和题意链路。"""
    errors: list[ValidationError] = []

    data_range = context.get("data_range")
    if not isinstance(data_range, dict):
        return [
            {
                "path": "context.data_range",
                "message": "机器语义上下文缺少data_range。",
            }
        ]

    range_start = parse_iso_date(
        data_range.get("start_date"),
        "context.data_range.start_date",
        errors,
    )
    range_end = parse_iso_date(
        data_range.get("end_date"),
        "context.data_range.end_date",
        errors,
    )
    if range_start is None or range_end is None:
        return errors

    status = plan.get("status")
    status_code = status.get("code") if isinstance(status, dict) else None
    operations = plan.get("operations")
    operation_list = operations if isinstance(operations, list) else []
    checks = plan.get("checks")
    check_list = checks if isinstance(checks, list) else []

    all_dates = collect_plan_dates(plan, errors)
    out_of_range = [
        (path, value)
        for path, value in all_dates
        if value < range_start or value > range_end
    ]

    if out_of_range and status_code != "data_unavailable":
        details = ", ".join(
            f"{path}={value.isoformat()}" for path, value in out_of_range
        )
        errors.append(
            {
                "path": "status.code",
                "message": (
                    "存在超出正式数据范围"
                    f"[{range_start.isoformat()}, {range_end.isoformat()}]"
                    f"的必要日期：{details}；必须使用data_unavailable。"
                ),
            }
        )

    if status_code == "data_unavailable" and not out_of_range:
        errors.append(
            {
                "path": "status.code",
                "message": "状态为data_unavailable，但计划中没有保留越界日期。",
            }
        )

    pending_concept_names = [
        str(item.get("name"))
        for item in context.get("business_concepts", [])
        if isinstance(item, dict)
        and item.get("status") == "待项目确认"
        and isinstance(item.get("name"), str)
    ]
    explicit_metric_names = [
        str(item.get("name"))
        for item in context.get("metrics", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and str(item.get("name")) in question
    ]
    explicit_metric_aliases = {
        "存款规模": "ZB001",
        "贷款规模": "ZB002",
        "网点平均存款规模": "ZB030",
        "日均存款余额": "ZB031",
    }
    concept_search_text = question
    protected_metric_phrases = [
        *explicit_metric_names,
        *[
            alias
            for alias in explicit_metric_aliases
            if alias in question
        ],
    ]
    for metric_name in sorted(
        protected_metric_phrases,
        key=len,
        reverse=True,
    ):
        concept_search_text = concept_search_text.replace(metric_name, "")
    matched_pending_concepts = [
        name for name in pending_concept_names if name in concept_search_text
    ]
    if (
        matched_pending_concepts
        and status_code != "pending_project_definition"
    ):
        errors.append(
            {
                "path": "status.code",
                "message": (
                    "问题包含待项目确认的业务概念："
                    + "、".join(matched_pending_concepts)
                    + "；必须使用pending_project_definition，"
                    "不得只执行其中部分明确指标。"
                ),
            }
        )
    if (
        status_code == "pending_project_definition"
        and pending_concept_names
        and not matched_pending_concepts
    ):
        errors.append(
            {
                "path": "status.code",
                "message": (
                    "问题中没有作为宽泛维度使用的待确认业务概念；"
                    "正式指标全名或明确别名应生成executable计划。"
                ),
            }
        )

    if status_code != "executable":
        if operation_list:
            errors.append(
                {
                    "path": "operations",
                    "message": "非executable状态的operations必须为空。",
                }
            )
        if check_list:
            errors.append(
                {
                    "path": "checks",
                    "message": "非executable状态的checks必须为空。",
                }
            )
        return errors

    official_institution_ids = {
        item.get("institution_id")
        for item in context.get("institutions", [])
        if isinstance(item, dict) and isinstance(item.get("institution_id"), str)
    }
    official_metric_ids = {
        item.get("metric_id")
        for item in context.get("metrics", [])
        if isinstance(item, dict) and isinstance(item.get("metric_id"), str)
    }
    official_concept_ids = {
        item.get("concept_id")
        for item in context.get("business_concepts", [])
        if isinstance(item, dict) and isinstance(item.get("concept_id"), str)
    }
    official_operator_ids = {
        item.get("operator_id")
        for item in context.get("operators", [])
        if isinstance(item, dict) and isinstance(item.get("operator_id"), str)
    }

    institutions_plan = plan.get("institutions")
    if isinstance(institutions_plan, dict):
        targets = institutions_plan.get("targets")
        if isinstance(targets, list):
            for index, target in enumerate(targets):
                institution_id = (
                    target.get("institution_id")
                    if isinstance(target, dict)
                    else None
                )
                if institution_id not in official_institution_ids:
                    errors.append(
                        {
                            "path": f"institutions.targets.{index}.institution_id",
                            "message": "机构编号不在正式语义上下文中。",
                        }
                    )
        comparison_population = institutions_plan.get("comparison_population")
        population_ids = (
            comparison_population.get("institution_ids")
            if isinstance(comparison_population, dict)
            else None
        )
        if isinstance(population_ids, list):
            for index, institution_id in enumerate(population_ids):
                if institution_id not in official_institution_ids:
                    errors.append(
                        {
                            "path": (
                                "institutions.comparison_population."
                                f"institution_ids.{index}"
                            ),
                            "message": "比较机构编号不在正式语义上下文中。",
                        }
                    )

    metrics_plan = plan.get("metrics")
    source_metric_ids: list[object] = []
    if isinstance(metrics_plan, dict):
        for field in ("requested_metric_ids", "source_metric_ids"):
            values = metrics_plan.get(field)
            if isinstance(values, list):
                if field == "source_metric_ids":
                    source_metric_ids = values
                for index, metric_id in enumerate(values):
                    if metric_id not in official_metric_ids:
                        errors.append(
                            {
                                "path": f"metrics.{field}.{index}",
                                "message": "指标编号不在正式语义上下文中。",
                            }
                        )
        concept_ids = metrics_plan.get("concept_ids")
        if isinstance(concept_ids, list):
            for index, concept_id in enumerate(concept_ids):
                if concept_id not in official_concept_ids:
                    errors.append(
                        {
                            "path": f"metrics.concept_ids.{index}",
                            "message": "业务概念编号不在正式语义上下文中。",
                        }
                    )

    if len(source_metric_ids) >= 2 and not has_check(plan, "metric_completeness"):
        errors.append(
            {
                "path": "checks",
                "message": "多基础指标计算必须加入metric_completeness。",
            }
        )

    seen_outputs: set[str] = set()
    for index, operation in enumerate(operation_list):
        if not isinstance(operation, dict):
            continue
        if operation.get("step") != index + 1:
            errors.append(
                {
                    "path": f"operations.{index}.step",
                    "message": "operations.step必须从1开始连续递增。",
                }
            )
        operator_id = operation.get("operator_id")
        if operator_id not in official_operator_ids:
            errors.append(
                {
                    "path": f"operations.{index}.operator_id",
                    "message": "算子编号不在正式语义上下文中。",
                }
            )
        output_ref = operation.get("output_ref")
        if not isinstance(output_ref, str) or not output_ref:
            errors.append(
                {
                    "path": f"operations.{index}.output_ref",
                    "message": "output_ref必须是非空字符串。",
                }
            )
        elif output_ref in seen_outputs:
            errors.append(
                {
                    "path": f"operations.{index}.output_ref",
                    "message": "output_ref在同一计划中必须唯一。",
                }
            )

        refs = operation.get("input_refs")
        refs = refs if isinstance(refs, list) else []
        if operator_id == "OP001":
            if refs and refs[0] not in official_metric_ids:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs.0",
                        "message": "OP001引用的指标不在正式语义上下文中。",
                    }
                )
        elif operator_id == "OP021":
            if refs:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP021不应引用前序计算结果。",
                    }
                )
        else:
            for ref_index, ref in enumerate(refs):
                if ref not in seen_outputs:
                    errors.append(
                        {
                            "path": f"operations.{index}.input_refs.{ref_index}",
                            "message": "input_refs只能引用已经产生的前序output_ref。",
                        }
                    )
        if isinstance(output_ref, str) and output_ref:
            seen_outputs.add(output_ref)

    output_to_operator: dict[str, str] = {}
    output_to_inputs: dict[str, list[str]] = {}
    operator_ids: list[str] = []

    for index, operation in enumerate(operation_list):
        if not isinstance(operation, dict):
            continue

        operator_id = operation.get("operator_id")
        if isinstance(operator_id, str):
            operator_ids.append(operator_id)

        output_ref = operation.get("output_ref")
        refs = operation.get("input_refs")
        input_refs = refs if isinstance(refs, list) else []

        if isinstance(output_ref, str) and isinstance(operator_id, str):
            output_to_operator[output_ref] = operator_id
            output_to_inputs[output_ref] = [
                ref for ref in input_refs if isinstance(ref, str)
            ]
        raw_parameters = operation.get("parameters")
        parameters = raw_parameters if isinstance(raw_parameters, dict) else {}

        if operator_id == "OP001":
            if (
                len(input_refs) != 1
                or not isinstance(input_refs[0], str)
                or re.fullmatch(r"ZB\d{3}", input_refs[0]) is None
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP001必须严格包含一个正式ZB指标编号。",
                    }
                )

            if "metric_id" in parameters:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.metric_id",
                        "message": "OP001指标必须写入input_refs，不得使用parameters.metric_id。",
                    }
                )

            institution_id = parameters.get("institution_id")
            institution_ids = parameters.get("institution_ids")
            has_single = isinstance(institution_id, str)
            has_multiple = isinstance(institution_ids, list)

            if has_single == has_multiple:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters",
                        "message": "OP001必须且只能使用institution_id或institution_ids之一。",
                    }
                )
            elif has_single and re.fullmatch(r"ORG\d{3}", institution_id) is None:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.institution_id",
                        "message": "institution_id必须是正式ORG编号，不能使用all占位符。",
                    }
                )
            elif has_multiple:
                invalid_ids = [
                    item
                    for item in institution_ids
                    if not isinstance(item, str)
                    or re.fullmatch(r"ORG\d{3}", item) is None
                ]
                if invalid_ids:
                    errors.append(
                        {
                            "path": f"operations.{index}.parameters.institution_ids",
                            "message": f"institution_ids包含非法机构编号：{invalid_ids}",
                        }
                    )

        if operator_id == "OP006":
            if len(input_refs) != 2:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP006必须严格包含两个输入。",
                    }
                )
            for field in ("numerator", "denominator"):
                if field not in parameters:
                    errors.append(
                        {
                            "path": f"operations.{index}.parameters.{field}",
                            "message": f"OP006缺少{field}。",
                        }
                    )
            multiplier = parameters.get("multiplier")
            if multiplier is not None and (
                isinstance(multiplier, bool)
                or not isinstance(multiplier, (int, float))
                or multiplier <= 0
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.multiplier",
                        "message": "OP006.multiplier必须是大于0的数值。",
                    }
                )
            result_unit = parameters.get("result_unit") or parameters.get("unit")
            if result_unit is not None and not isinstance(result_unit, str):
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.result_unit",
                        "message": "OP006结果单位必须是字符串。",
                    }
                )

        if operator_id == "OP007" and len(input_refs) != 2:
            errors.append(
                {
                    "path": f"operations.{index}.input_refs",
                    "message": "OP007必须按[本期值, 基期值]提供两个输入。",
                }
            )

        if operator_id == "OP009" and not input_refs:
            errors.append(
                {
                    "path": f"operations.{index}.input_refs",
                    "message": "OP009至少需要一个期间记录输入。",
                }
            )

        if operator_id == "OP011":
            if not input_refs:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP011至少需要一个记录输入。",
                    }
                )
            if parameters.get("order") not in {
                "ascending",
                "descending",
            }:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.order",
                        "message": "OP011.order只能是ascending或descending。",
                    }
                )

        if operator_id == "OP012":
            if not input_refs:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP012至少需要一个记录输入。",
                    }
                )
            if parameters.get("performance_direction") not in {
                "higher_is_better",
                "lower_is_better",
            }:
                errors.append(
                    {
                        "path": (
                            f"operations.{index}."
                            "parameters.performance_direction"
                        ),
                        "message": (
                            "OP012必须明确higher_is_better或"
                            "lower_is_better。"
                        ),
                    }
                )

        if operator_id == "OP013":
            if parameters.get("direction") not in {"top", "bottom"}:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.direction",
                        "message": "OP013.direction只能是top或bottom。",
                    }
                )
            if (
                not isinstance(parameters.get("n"), int)
                or parameters.get("n", 0) < 1
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.n",
                        "message": "OP013.n必须是正整数。",
                    }
                )
            if (
                len(input_refs) != 1
                or output_to_operator.get(input_refs[0])
                not in {"OP011", "OP012"}
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP013必须接收OP011或OP012的唯一输出。",
                    }
                )

        if operator_id == "OP014":
            if len(input_refs) != 1:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP014必须严格接收一个记录序列。",
                    }
                )
            if parameters.get("type") not in {"max", "min"}:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.type",
                        "message": "OP014.type只能是max或min。",
                    }
                )

        if operator_id == "OP016" and len(input_refs) != 1:
            errors.append(
                {
                    "path": f"operations.{index}.input_refs",
                    "message": (
                        "OP016只能接收一个待筛选记录集合；"
                        "与动态基准比较时必须先用OP003生成差值。"
                    ),
                }
            )

        if operator_id == "OP018" and len(input_refs) != 1:
            errors.append(
                {
                    "path": f"operations.{index}.input_refs",
                    "message": "OP018必须严格接收一个时间序列。",
                }
            )

        if operator_id in {"OP015", "OP016"}:
            for field in (
                "comparison_operator",
                "threshold",
                "unit",
            ):
                if field not in parameters:
                    errors.append(
                        {
                            "path": f"operations.{index}.parameters.{field}",
                            "message": f"{operator_id}缺少{field}。",
                        }
                    )
            if parameters.get("comparison_operator") not in {
                ">",
                ">=",
                "<",
                "<=",
                "=",
                "!=",
            }:
                errors.append(
                    {
                        "path": (
                            f"operations.{index}."
                            "parameters.comparison_operator"
                        ),
                        "message": "比较符必须使用标准符号。",
                    }
                )
            if "condition" in parameters or "comparison" in parameters:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters",
                        "message": "不得使用condition或comparison自然语言字段。",
                    }
                )

        if operator_id == "OP017":
            if len(input_refs) != 1:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP017必须严格接收一个待计数结果。",
                    }
                )
            count_by = parameters.get("count_by")
            if count_by is not None and count_by not in {
                "date",
                "institution",
                "record",
            }:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.count_by",
                        "message": "OP017.count_by只能是date、institution或record。",
                    }
                )

        if operator_id == "OP019":
            if len(input_refs) < 2:
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": "OP019至少需要两个独立结果。",
                    }
                )
            for ref in input_refs:
                if output_to_operator.get(ref) != "OP018":
                    continue
                source_refs = output_to_inputs.get(ref, [])
                redundant = [
                    source_ref
                    for source_ref in source_refs
                    if source_ref in input_refs
                ]
                if redundant:
                    errors.append(
                        {
                            "path": f"operations.{index}.input_refs",
                            "message": (
                                "OP018结果已经包含原始时间序列，OP019不得再次"
                                f"合并其原始输入：{redundant}。"
                            ),
                        }
                    )

        if operator_id == "OP021":
            if parameters.get("type") not in {
                "previous_month_end",
                "previous_quarter_end",
                "previous_year_same_period",
                "previous_year_end",
                "year_begin_base",
            }:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.type",
                        "message": "OP021.type不合法。",
                    }
                )
            if not isinstance(parameters.get("reference_date"), str):
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.reference_date",
                        "message": "OP021缺少reference_date。",
                    }
                )

    operator_set = set(operator_ids)
    final_operator = operator_ids[-1] if operator_ids else None

    metrics_plan = plan.get("metrics")
    requested_metric_ids = (
        metrics_plan.get("requested_metric_ids", [])
        if isinstance(metrics_plan, dict)
        else []
    )
    source_metric_ids = (
        metrics_plan.get("source_metric_ids", [])
        if isinstance(metrics_plan, dict)
        else []
    )
    output_plan = plan.get("output")
    answer_type = (
        output_plan.get("answer_type")
        if isinstance(output_plan, dict)
        else None
    )

    op001_operations = [
        item
        for item in operation_list
        if isinstance(item, dict)
        and item.get("operator_id") == "OP001"
    ]
    op011_operations = [
        item
        for item in operation_list
        if isinstance(item, dict)
        and item.get("operator_id") == "OP011"
    ]
    op013_operations = [
        item
        for item in operation_list
        if isinstance(item, dict)
        and item.get("operator_id") == "OP013"
    ]
    op019_operations = [
        item
        for item in operation_list
        if isinstance(item, dict)
        and item.get("operator_id") == "OP019"
    ]

    op001_metric_to_outputs: dict[str, list[str]] = {}
    for operation in op001_operations:
        refs = operation.get("input_refs")
        output_ref = operation.get("output_ref")
        if (
            isinstance(refs, list)
            and len(refs) == 1
            and isinstance(refs[0], str)
            and isinstance(output_ref, str)
        ):
            op001_metric_to_outputs.setdefault(refs[0], []).append(output_ref)

    op001_metric_ids = set(op001_metric_to_outputs)
    source_metric_id_set = {
        item for item in source_metric_ids if isinstance(item, str)
    }
    if source_metric_id_set != op001_metric_ids:
        missing_reads = sorted(source_metric_id_set - op001_metric_ids)
        undeclared_reads = sorted(op001_metric_ids - source_metric_id_set)
        details: list[str] = []
        if missing_reads:
            details.append(f"未被OP001读取：{missing_reads}")
        if undeclared_reads:
            details.append(f"未在source_metric_ids声明：{undeclared_reads}")
        errors.append(
            {
                "path": "metrics.source_metric_ids",
                "message": (
                    "source_metric_ids必须与全部OP001实际读取的基础指标完全一致；"
                    + "；".join(details)
                    + "。"
                ),
            }
        )

    metric_name_to_id = {
        str(item.get("name")): str(item.get("metric_id"))
        for item in context.get("metrics", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("metric_id"), str)
    }
    stored_metric_ids = {
        metric_id
        for metric_id in official_metric_ids
        if isinstance(metric_id, str)
        and re.fullmatch(r"ZB\d{3}", metric_id)
        and int(metric_id[2:]) <= 21
    }
    directly_requested_stored_metrics = {
        metric_id
        for metric_name, metric_id in metric_name_to_id.items()
        if metric_id in stored_metric_ids and metric_name in question
    }
    asks_direct_metric_values = (
        re.search(r"(?:分别|各自|各)?是多少|为多少", question) is not None
    )
    if directly_requested_stored_metrics and asks_direct_metric_values:
        extra_sources = source_metric_id_set - directly_requested_stored_metrics
        missing_sources = directly_requested_stored_metrics - source_metric_id_set
        if extra_sources or missing_sources:
            errors.append(
                {
                    "path": "metrics.source_metric_ids",
                    "message": (
                        "直接询问正式基础指标当前值时，source_metric_ids必须只包含"
                        "题目明确要求的指标，不得加入分子、分母重新推导。"
                    ),
                }
            )

        if len(directly_requested_stored_metrics) >= 2:
            final_refs = (
                op019_operations[-1].get("input_refs", [])
                if op019_operations
                else []
            )
            direct_output_refs = {
                output_ref
                for metric_id in directly_requested_stored_metrics
                for output_ref in op001_metric_to_outputs.get(metric_id, [])
            }
            if (
                final_operator != "OP019"
                or not isinstance(final_refs, list)
                or not direct_output_refs.issubset(set(final_refs))
            ):
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "同时询问多个正式基础指标当前值时，必须由OP001直接读取"
                            "每个指标，并由最后一步OP019直接合并这些OP001输出；"
                            "不得合并重新计算的替代结果。"
                        ),
                    }
                )

    asks_daily_deposit_average = (
        "日均存款余额" in question
        or "ZB031" in requested_metric_ids
    )
    if asks_daily_deposit_average:
        if "ZB001" not in source_metric_ids:
            errors.append(
                {
                    "path": "metrics.source_metric_ids",
                    "message": (
                        "日均存款余额必须以ZB001各项存款余额为基础数据。"
                    ),
                }
            )
        if "ZB031" in source_metric_ids:
            errors.append(
                {
                    "path": "metrics.source_metric_ids",
                    "message": (
                        "ZB031是派生指标，不得作为OP001基础读取指标。"
                    ),
                }
            )
        if "OP009" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "日均存款余额必须使用OP009计算期间均值。",
                }
            )
        for index, operation in enumerate(operation_list):
            if (
                isinstance(operation, dict)
                and operation.get("operator_id") == "OP001"
                and operation.get("input_refs") == ["ZB031"]
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": (
                            "不得直接读取ZB031；应读取ZB001日序列后使用OP009。"
                        ),
                    }
                )

    asks_absolute_change = (
        re.search(r"(变动|变化)(了)?多少|增加多少|减少多少", question)
        is not None
        and "变化情况" not in question
        and not any(
            phrase in question
            for phrase in (
                "增幅",
                "增长率",
                "变化率",
                "百分之多少",
            )
        )
    )
    if asks_absolute_change:
        if "OP003" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "“变动了多少／变化了多少”默认返回绝对差额，"
                        "必须使用OP003。"
                    ),
                }
            )
        if "OP007" in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "该题未要求增幅或变化率，不得使用OP007替代绝对差额。"
                    ),
                }
            )

    asks_multiple_explicit_results = (
        "分别" in question
        or (
            "合计" in question
            and any(word in question for word in ("和", "及"))
        )
    )
    if asks_multiple_explicit_results:
        if final_operator != "OP019":
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "题目要求多个明确结果，必须以OP019合并作为最后一步。"
                    ),
                }
            )
        elif op019_operations:
            final_refs = op019_operations[-1].get("input_refs", [])
            minimum_inputs = 3 if "合计" in question else 2
            if (
                not isinstance(final_refs, list)
                or len(final_refs) < minimum_inputs
            ):
                errors.append(
                    {
                        "path": (
                            f"operations.{len(operation_list) - 1}.input_refs"
                        ),
                        "message": (
                            f"最终OP019至少应合并{minimum_inputs}个用户要求的结果。"
                        ),
                    }
                )

    asks_last_numeric_rank = any(
        phrase in question
        for phrase in (
            "排最后一名",
            "最后一名",
            "排名最后",
        )
    ) and not any(
        phrase in question
        for phrase in ("最差", "控制得最差")
    )
    if asks_last_numeric_rank:
        if not op011_operations or not op013_operations:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "纯数值最后一名必须使用OP011降序排名后由OP013取bottom。"
                    ),
                }
            )
        else:
            order = op011_operations[-1].get("parameters", {}).get("order")
            direction = (
                op013_operations[-1]
                .get("parameters", {})
                .get("direction")
            )
            if order != "descending":
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "纯数值排名第1名定义为数值最高，OP011.order必须为descending。"
                        ),
                    }
                )
            if direction != "bottom":
                errors.append(
                    {
                        "path": "operations",
                        "message": "排最后一名时OP013.direction必须为bottom。",
                    }
                )

    asks_first_numeric_rank = any(
        phrase in question
        for phrase in (
            "排第一",
            "排名第一",
            "第一名",
        )
    ) and not any(
        phrase in question
        for phrase in ("最好", "控制得最好")
    )
    if asks_first_numeric_rank and op011_operations and op013_operations:
        order = op011_operations[-1].get("parameters", {}).get("order")
        direction = (
            op013_operations[-1]
            .get("parameters", {})
            .get("direction")
        )
        if order != "descending" or direction != "top":
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "纯数值第一名必须使用OP011降序排名并由OP013取top。"
                    ),
                }
            )

    asks_target_daily_vs_province = (
        "全省均值" in question
        and "多少天" in question
    )
    if asks_target_daily_vs_province:
        target_ids = []
        if isinstance(institutions_plan, dict):
            raw_targets = institutions_plan.get("targets")
            if isinstance(raw_targets, list):
                target_ids = [
                    item.get("institution_id")
                    for item in raw_targets
                    if isinstance(item, dict)
                    and isinstance(item.get("institution_id"), str)
                ]
        single_target_reads = []
        province_reads = []
        for operation in op001_operations:
            parameters = operation.get("parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            institution_id = parameters.get("institution_id")
            institution_ids = parameters.get("institution_ids")
            if institution_id in target_ids:
                single_target_reads.append(operation)
            if (
                isinstance(institution_ids, list)
                and set(institution_ids) == official_institution_ids
            ):
                province_reads.append(operation)
        if not single_target_reads:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "目标机构逐日与全省均值比较时，必须单独读取目标机构日序列。"
                    ),
                }
            )
        if not province_reads:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "目标机构逐日与全省均值比较时，必须另行读取全省13家日序列。"
                    ),
                }
            )
        op010_outputs = {
            item.get("output_ref")
            for item in operation_list
            if isinstance(item, dict)
            and item.get("operator_id") == "OP010"
        }
        target_read_outputs = {
            item.get("output_ref")
            for item in single_target_reads
        }
        valid_difference = False
        for operation in operation_list:
            if (
                isinstance(operation, dict)
                and operation.get("operator_id") == "OP003"
            ):
                refs = operation.get("input_refs")
                if (
                    isinstance(refs, list)
                    and len(refs) == 2
                    and refs[0] in target_read_outputs
                    and refs[1] in op010_outputs
                ):
                    valid_difference = True
                    break
        if not valid_difference:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "逐日比较必须由OP003按[目标机构日序列, 全省当日均值]计算差值。"
                    ),
                }
            )

    asks_period_average_top_bottom = (
        any(word in question for word in ("均值排名", "平均值排名", "日均排名"))
        and any(word in question for word in ("前三", "前3"))
        and any(word in question for word in ("后三", "后3"))
    )
    if asks_period_average_top_bottom:
        for required_operator in ("OP009", "OP011", "OP013", "OP019"):
            if required_operator not in operator_set:
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "期间均值同时返回前三和后三必须包含"
                            f"OP009、OP011、两个OP013和OP019；当前缺少{required_operator}。"
                        ),
                    }
                )
        op013_directions = [
            item.get("parameters", {}).get("direction")
            for item in operation_list
            if isinstance(item, dict)
            and item.get("operator_id") == "OP013"
            and isinstance(item.get("parameters"), dict)
        ]
        if "top" not in op013_directions or "bottom" not in op013_directions:
            errors.append(
                {
                    "path": "operations",
                    "message": "期间均值前三和后三必须分别生成direction=top和direction=bottom的OP013。",
                }
            )
        if final_operator != "OP019":
            errors.append(
                {
                    "path": "operations",
                    "message": "期间均值前三和后三必须以OP019合并作为最后一步。",
                }
            )

    asks_month_and_year_comparison = (
        ("环比" in question or "较上月" in question)
        and ("同比" in question or "较去年同期" in question)
    )
    if asks_month_and_year_comparison:
        if operator_ids.count("OP021") < 2:
            errors.append(
                {
                    "path": "operations",
                    "message": "环比和同比必须分别使用两个OP021定位上月末与去年同期。",
                }
            )
        if operator_ids.count("OP007") < 2:
            errors.append(
                {
                    "path": "operations",
                    "message": "环比和同比必须分别生成两个OP007增幅结果。",
                }
            )
        if final_operator != "OP019":
            errors.append(
                {
                    "path": "operations",
                    "message": "环比和同比必须以OP019合并作为最后一步。",
                }
            )
        else:
            final_operation = operation_list[-1] if operation_list else {}
            final_refs = (
                final_operation.get("input_refs", [])
                if isinstance(final_operation, dict)
                else []
            )
            explicit_current_dates: set[str] = set()
            time_plan = plan.get("time")
            if isinstance(time_plan, dict):
                dates = time_plan.get("dates")
                if isinstance(dates, list):
                    explicit_current_dates.update(
                        item for item in dates if isinstance(item, str)
                    )
                periods = time_plan.get("comparison_periods")
                if isinstance(periods, list):
                    for period in periods:
                        if (
                            isinstance(period, dict)
                            and period.get("type") == "explicit"
                            and isinstance(period.get("date"), str)
                        ):
                            explicit_current_dates.add(period["date"])

            current_value_refs = {
                item.get("output_ref")
                for item in operation_list
                if isinstance(item, dict)
                and item.get("operator_id") == "OP001"
                and isinstance(item.get("output_ref"), str)
                and isinstance(item.get("parameters"), dict)
                and item["parameters"].get("date") in explicit_current_dates
            }
            if not any(ref in current_value_refs for ref in final_refs):
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "环比和同比最终结果必须同时合并本期原始值、"
                            "环比结果和同比结果。"
                        ),
                    }
                )

    asks_branch_average_deposit = "网点平均存款规模" in question
    if asks_branch_average_deposit:
        metrics = plan.get("metrics")
        source_metrics = (
            set(metrics.get("source_metric_ids", []))
            if isinstance(metrics, dict)
            else set()
        )
        if not {"ZB001", "ZB019"}.issubset(source_metrics):
            errors.append(
                {
                    "path": "metrics.source_metric_ids",
                    "message": "网点平均存款规模必须读取ZB001各项存款余额和ZB019网点数量。",
                }
            )
        for required_operator in ("OP020", "OP006"):
            if required_operator not in operator_set:
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "网点平均存款规模必须先用OP020把亿元换算为万元，"
                            f"再用OP006除以网点数量；当前缺少{required_operator}。"
                        ),
                    }
                )
        op020_valid = any(
            isinstance(item, dict)
            and item.get("operator_id") == "OP020"
            and isinstance(item.get("parameters"), dict)
            and item["parameters"].get("to_unit") == "万元"
            for item in operation_list
        )
        if not op020_valid:
            errors.append(
                {
                    "path": "operations",
                    "message": "网点平均存款规模中的OP020.to_unit必须为万元。",
                }
            )
        op006_valid = any(
            isinstance(item, dict)
            and item.get("operator_id") == "OP006"
            and isinstance(item.get("parameters"), dict)
            and item["parameters"].get("multiplier", 1) == 1
            and (
                item["parameters"].get("result_unit")
                or item["parameters"].get("unit")
            )
            == "万元/网点"
            for item in operation_list
        )
        if not op006_valid:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "网点平均存款规模中的OP006必须设置"
                        "multiplier=1、result_unit=万元/网点。"
                    ),
                }
            )

    op014_types = [
        operation.get("parameters", {}).get("type")
        for operation in operation_list
        if isinstance(operation, dict)
        and operation.get("operator_id") == "OP014"
        and isinstance(operation.get("parameters"), dict)
    ]
    asks_high_extreme = any(
        word in question for word in ("最高", "最大")
    )
    asks_low_extreme = any(
        word in question for word in ("最低", "最小")
    )

    if asks_high_extreme and asks_low_extreme:
        if "max" not in op014_types or "min" not in op014_types:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "题目同时要求最高值和最低值，必须分别使用"
                        "type=max和type=min的两个OP014。"
                    ),
                }
            )
        if "OP019" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "最高值和最低值必须使用OP019合并。",
                }
            )
        elif final_operator != "OP019":
            errors.append(
                {
                    "path": "operations",
                    "message": "同时返回最高值和最低值时，最后一步必须是OP019。",
                }
            )

    discrete_series_phrases = (
        "逐季变化",
        "逐月变化",
        "逐日变化",
        "逐年变化",
        "各季度末数值",
        "各月末数值",
        "各日数值",
        "各年末数值",
    )
    asks_discrete_series = any(
        phrase in question for phrase in discrete_series_phrases
    )
    if asks_discrete_series:
        series_reads = [
            operation
            for operation in operation_list
            if isinstance(operation, dict)
            and operation.get("operator_id") == "OP001"
            and isinstance(operation.get("parameters"), dict)
            and isinstance(operation["parameters"].get("dates"), list)
            and len(operation["parameters"]["dates"]) >= 2
        ]
        if not series_reads:
            errors.append(
                {
                    "path": "operations",
                    "message": (
                        "离散时间序列必须使用一个OP001及parameters.dates"
                        "读取完整序列，不能拆成多个单点读取后直接分析。"
                    ),
                }
            )

    asks_trend = any(
        phrase in question
        for phrase in (
            "走势",
            "趋势",
            "逐季变化",
            "逐月变化",
            "逐日变化",
            "逐年变化",
            "波动",
        )
    )
    if asks_trend:
        if "OP018" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "时间变化分析必须使用OP018。",
                }
            )
        if not has_check(plan, "unrounded_comparison"):
            errors.append(
                {
                    "path": "checks",
                    "message": "趋势分析缺少unrounded_comparison。",
                }
            )

    if (
        asks_discrete_series
        and (asks_high_extreme or asks_low_extreme)
    ):
        if "OP014" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "序列极值问题必须使用OP014。",
                }
            )
        if "OP019" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "同时返回时间序列分析和极值时必须使用OP019合并。",
                }
            )
        elif final_operator != "OP019":
            errors.append(
                {
                    "path": "operations",
                    "message": "序列分析与极值的复合结果必须以OP019作为最后一步。",
                }
            )

    dynamic_province_baseline = (
        "全省均值" in question
        and any(
            word in question
            for word in ("高于", "低于", "超过", "不高于", "不低于")
        )
    )
    if dynamic_province_baseline:
        for required_operator in ("OP010", "OP003", "OP016"):
            if required_operator not in operator_set:
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "与全省均值逐记录比较必须依次包含"
                            f"OP010、OP003和OP016；当前缺少{required_operator}。"
                        ),
                    }
                )

        op003_outputs = {
            operation.get("output_ref")
            for operation in operation_list
            if isinstance(operation, dict)
            and operation.get("operator_id") == "OP003"
        }
        for index, operation in enumerate(operation_list):
            if (
                not isinstance(operation, dict)
                or operation.get("operator_id") != "OP016"
            ):
                continue
            refs = operation.get("input_refs")
            parameters = operation.get("parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            if (
                not isinstance(refs, list)
                or len(refs) != 1
                or refs[0] not in op003_outputs
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": (
                            "动态全省均值筛选的OP016必须只接收"
                            "OP003产生的差值序列。"
                        ),
                    }
                )
            if parameters.get("threshold") != 0:
                errors.append(
                    {
                        "path": f"operations.{index}.parameters.threshold",
                        "message": "动态基准差值筛选必须以0为threshold。",
                    }
                )

        if "多少天" in question and "OP017" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "询问满足条件的天数必须使用OP017计数。",
                }
            )
        if "多少天" in question:
            for index, operation in enumerate(operation_list):
                if (
                    not isinstance(operation, dict)
                    or operation.get("operator_id") != "OP017"
                ):
                    continue
                parameters = operation.get("parameters")
                parameters = parameters if isinstance(parameters, dict) else {}
                if parameters.get("count_by") != "date":
                    errors.append(
                        {
                            "path": f"operations.{index}.parameters.count_by",
                            "message": "询问天数时OP017.count_by必须为date。",
                        }
                    )
                if parameters.get("unit") != "天":
                    errors.append(
                        {
                            "path": f"operations.{index}.parameters.unit",
                            "message": "询问天数时OP017.unit必须为天。",
                        }
                    )

    institutions = plan.get("institutions")
    population = (
        institutions.get("comparison_population", {})
        if isinstance(institutions, dict)
        else {}
    )
    population_type = (
        population.get("type") if isinstance(population, dict) else None
    )

    asks_province_cross_section_average = any(
        phrase in question
        for phrase in ("全省均值", "全省平均值", "全省平均")
    )
    if (
        population_type == "all_official_institutions"
        and asks_province_cross_section_average
        and "OP010" not in operator_set
    ):
        errors.append(
            {
                "path": "operations",
                "message": "全省13家机构均值必须使用OP010。",
            }
        )

    relative_count = 0
    relative_count += int("环比" in question or "较上月" in question)
    relative_count += int("同比" in question or "较去年同期" in question)
    relative_count += int("较上季" in question)
    relative_count += int("较年初" in question)

    actual_op021 = operator_ids.count("OP021")
    if relative_count and actual_op021 < relative_count:
        errors.append(
            {
                "path": "operations",
                "message": (
                    f"题目包含{relative_count}个相对基期，至少需要"
                    f"{relative_count}个OP021，实际为{actual_op021}个。"
                ),
            }
        )

    asks_count_and_detail = (
        "有几家" in question
        and any(word in question for word in ("分别", "哪些", "哪几家"))
    )
    if asks_count_and_detail:
        for required_operator in ("OP016", "OP017", "OP019"):
            if required_operator not in operator_set:
                errors.append(
                    {
                        "path": "operations",
                        "message": (
                            "筛选明细和数量必须包含OP016、OP017、OP019；"
                            f"当前缺少{required_operator}。"
                        ),
                    }
                )

    if (
        "环比" in question
        and "同比" in question
        and "OP019" not in operator_set
    ):
        errors.append(
            {
                "path": "operations",
                "message": "环比和同比结果必须使用OP019合并。",
            }
        )

    if any(word in question for word in ("监管要求", "最低要求")):
        if "OP015" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "监管阈值判断必须使用OP015。",
                }
            )

        op015_outputs = {
            item.get("output_ref")
            for item in operation_list
            if isinstance(item, dict)
            and item.get("operator_id") == "OP015"
        }
        for index, operation in enumerate(operation_list):
            if (
                isinstance(operation, dict)
                and operation.get("operator_id") == "OP003"
                and any(
                    ref in op015_outputs
                    for ref in operation.get("input_refs", [])
                )
            ):
                errors.append(
                    {
                        "path": f"operations.{index}.input_refs",
                        "message": (
                            "OP015已返回达标结论和差距，"
                            "不得再把其输出交给OP003。"
                        ),
                    }
                )

        metrics = plan.get("metrics")
        requested = (
            metrics.get("requested_metric_ids", [])
            if isinstance(metrics, dict)
            else []
        )
        expected_thresholds = {
            "ZB013": (5, "<"),
            "ZB015": (150, ">="),
            "ZB016": (10.5, ">="),
        }
        for index, operation in enumerate(operation_list):
            if (
                isinstance(operation, dict)
                and operation.get("operator_id") == "OP015"
                and requested
                and requested[0] in expected_thresholds
            ):
                expected_threshold, expected_operator = (
                    expected_thresholds[requested[0]]
                )
                parameters = operation.get("parameters", {})
                if parameters.get("threshold") != expected_threshold:
                    errors.append(
                        {
                            "path": (
                                f"operations.{index}.parameters.threshold"
                            ),
                            "message": "监管阈值与正式语言规则不一致。",
                        }
                    )
                if (
                    parameters.get("comparison_operator")
                    != expected_operator
                ):
                    errors.append(
                        {
                            "path": (
                                f"operations.{index}."
                                "parameters.comparison_operator"
                            ),
                            "message": "监管比较符与正式语言规则不一致。",
                        }
                    )

        if not has_check(plan, "unrounded_comparison"):
            errors.append(
                {
                    "path": "checks",
                    "message": "监管阈值判断缺少unrounded_comparison。",
                }
            )

    if any(word in question for word in ("最好", "最差", "控制得最好")):
        if "OP012" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "绩效好坏必须使用OP012。",
                }
            )
        if (
            re.search(r"\d+家|前\d+|后\d+", question)
            and "OP013" not in operator_set
        ):
            errors.append(
                {
                    "path": "operations",
                    "message": "绩效Top/Bottom N还必须使用OP013。",
                }
            )

    numeric_top_n = (
        re.search(r"(最高|最低).{0,4}\d+家", question) is not None
        and not any(
            word in question for word in ("最好", "最差", "控制得最好")
        )
    )
    if numeric_top_n and not {"OP011", "OP013"}.issubset(operator_set):
        errors.append(
            {
                "path": "operations",
                "message": "纯数值Top/Bottom N必须先OP011再OP013。",
            }
        )

    asks_extreme_day = (
        "哪一天" in question
        and any(word in question for word in ("最高", "最低", "最大", "最小"))
    )
    if asks_extreme_day:
        time_plan = plan.get("time")
        if not isinstance(time_plan, dict):
            errors.append({"path": "time", "message": "缺少time对象。"})
        else:
            if time_plan.get("mode") != "range":
                errors.append(
                    {
                        "path": "time.mode",
                        "message": "期间极值日期必须使用range。",
                    }
                )
            if time_plan.get("grain") != "day":
                errors.append(
                    {
                        "path": "time.grain",
                        "message": "询问哪一天必须使用day粒度。",
                    }
                )
            if (
                not time_plan.get("start_date")
                or not time_plan.get("end_date")
            ):
                errors.append(
                    {
                        "path": "time",
                        "message": "期间极值必须填写起止日期。",
                    }
                )

            half_year_match = re.search(
                r"(\d{4})年(上半年|下半年)",
                question,
            )
            if half_year_match:
                year = int(half_year_match.group(1))
                half = half_year_match.group(2)
                expected_start = (
                    f"{year}-01-01"
                    if half == "上半年"
                    else f"{year}-07-01"
                )
                expected_end = (
                    f"{year}-06-30"
                    if half == "上半年"
                    else f"{year}-12-31"
                )
                if time_plan.get("start_date") != expected_start:
                    errors.append(
                        {
                            "path": "time.start_date",
                            "message": f"正确起始日期应为{expected_start}。",
                        }
                    )
                if time_plan.get("end_date") != expected_end:
                    errors.append(
                        {
                            "path": "time.end_date",
                            "message": f"正确结束日期应为{expected_end}。",
                        }
                    )

        if "OP014" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "期间最高或最低日期必须使用OP014。",
                }
            )
        for check_type in (
            "date_completeness",
            "unrounded_comparison",
        ):
            if not has_check(plan, check_type):
                errors.append(
                    {
                        "path": "checks",
                        "message": f"期间极值缺少{check_type}。",
                    }
                )

    metric_check_types = {
        "record_exists",
        "metric_completeness",
        "denominator_nonzero",
        "unit_consistency",
        "unrounded_comparison",
        "tie_preservation",
    }
    for index, check in enumerate(check_list):
        if not isinstance(check, dict):
            continue
        check_type = check.get("type")
        parameters = check.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}

        if "metric_id" in parameters:
            errors.append(
                {
                    "path": f"checks.{index}.parameters.metric_id",
                    "message": "检查参数不得使用metric_id，必须统一使用metric_ids数组。",
                }
            )

        if check_type in metric_check_types:
            metric_ids = parameters.get("metric_ids")
            if not isinstance(metric_ids, list) or not metric_ids:
                errors.append(
                    {
                        "path": f"checks.{index}.parameters.metric_ids",
                        "message": f"{check_type}必须提供非空metric_ids数组。",
                    }
                )

    return errors
