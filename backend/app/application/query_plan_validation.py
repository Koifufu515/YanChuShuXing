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
    clarification_questions = status.get("questions", []) if isinstance(status, dict) else []
    operations = plan.get("operations")
    operation_list = operations if isinstance(operations, list) else []
    checks = plan.get("checks")
    check_list = checks if isinstance(checks, list) else []

    if status_code == "clarification_required" and isinstance(clarification_questions, list):
        fields = [item.get("field") for item in clarification_questions if isinstance(item, dict)]
        if len(fields) != len(set(fields)):
            errors.append(
                {
                    "path": "status.questions",
                    "message": "结构化澄清问题的field不得重复。",
                }
            )
        official_institution_ids = {
            item.get("institution_id")
            for item in context.get("institutions", [])
            if isinstance(item, dict)
        }
        official_metric_ids = {
            item.get("metric_id")
            for item in context.get("metrics", [])
            if isinstance(item, dict)
        }
        official_operator_ids = {
            item.get("operator_id")
            for item in context.get("operators", [])
            if isinstance(item, dict)
        }
        for index, item in enumerate(clarification_questions):
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "")
            option_values = {
                option.get("value")
                for option in item.get("options", [])
                if isinstance(option, dict)
            }
            if "metric" in field and not option_values <= official_metric_ids:
                errors.append(
                    {
                        "path": f"status.questions.{index}.options",
                        "message": "指标澄清候选项只能使用正式ZB指标编号。",
                    }
                )
            if "institution" in field and not option_values <= (
                official_institution_ids | {"all_official_institutions"}
            ):
                errors.append(
                    {
                        "path": f"status.questions.{index}.options",
                        "message": "机构澄清候选项只能使用正式ORG编号或正式全机构范围。",
                    }
                )
            if field == "analysis_operator" and not option_values <= official_operator_ids:
                errors.append(
                    {
                        "path": f"status.questions.{index}.options",
                        "message": "分析算子候选项只能使用正式OP编号。",
                    }
                )
    elif clarification_questions:
        errors.append(
            {
                "path": "status.questions",
                "message": "只有clarification_required状态可以返回澄清问题。",
            }
        )

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
    operator_ids: list[str] = []

    for index, operation in enumerate(operation_list):
        if not isinstance(operation, dict):
            continue

        operator_id = operation.get("operator_id")
        if isinstance(operator_id, str):
            operator_ids.append(operator_id)

        output_ref = operation.get("output_ref")
        if isinstance(output_ref, str) and isinstance(operator_id, str):
            output_to_operator[output_ref] = operator_id

        refs = operation.get("input_refs")
        input_refs = refs if isinstance(refs, list) else []
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

        if operator_id == "OP007" and len(input_refs) != 2:
            errors.append(
                {
                    "path": f"operations.{index}.input_refs",
                    "message": "OP007必须按[本期值, 基期值]提供两个输入。",
                }
            )

        if operator_id == "OP011":
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

        if operator_id == "OP019" and len(input_refs) < 2:
            errors.append(
                {
                    "path": f"operations.{index}.input_refs",
                    "message": "OP019至少需要两个独立结果。",
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

    institutions = plan.get("institutions")
    population = (
        institutions.get("comparison_population", {})
        if isinstance(institutions, dict)
        else {}
    )
    population_type = (
        population.get("type") if isinstance(population, dict) else None
    )

    if (
        population_type == "all_official_institutions"
        and any(word in question for word in ("平均", "均值"))
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

    if any(word in question for word in ("走势", "趋势")):
        if "OP018" not in operator_set:
            errors.append(
                {
                    "path": "operations",
                    "message": "走势或趋势问题必须使用OP018。",
                }
            )
        if not has_check(plan, "unrounded_comparison"):
            errors.append(
                {
                    "path": "checks",
                    "message": "趋势分析缺少unrounded_comparison。",
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
