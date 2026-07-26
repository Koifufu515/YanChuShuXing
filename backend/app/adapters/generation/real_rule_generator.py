from __future__ import annotations

import re
from datetime import date

import yaml

from app.application.errors import (
    ConfigurationError,
    RuleNotMatchedError,
    UnsupportedQuestionError,
)
from app.application.models import (
    GeneratedSQL,
    QueryContext,
    QueryMetadata,
    SemanticMetadata,
)


SINGLE_PATTERN = re.compile(
    r"^查询(?P<institution>.+?)在(?P<data_date>\d{4}-\d{2}-\d{2})的(?P<metric>.+)$"
)
RANKING_PATTERN = re.compile(
    r"^查询(?P<data_date>\d{4}-\d{2}-\d{2})(?P<metric>.+?)机构排名$"
)
TREND_PATTERN = re.compile(
    r"^查询(?P<institution>.+?)从(?P<start_date>\d{4}-\d{2}-\d{2})到"
    r"(?P<end_date>\d{4}-\d{2}-\d{2})的(?P<metric>.+?)趋势$"
)
CONFIRMED_GROWTH_RANKING_PATTERN = re.compile(
    r"^__confirmed_growth_ranking__:(?P<metric_id>[A-Za-z0-9_-]+):"
    r"(?P<start_date>\d{4}-\d{2}-\d{2}):(?P<end_date>\d{4}-\d{2}-\d{2}):"
    r"(?P<method>absolute_change)$"
)


class RealRuleSQLGenerator:
    """Three audited, parameterized rules over the official business cube."""

    name = "real-rule-v2"

    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        compact = _normalize(question)
        metrics, institutions = _catalogs(context)

        matched = CONFIRMED_GROWTH_RANKING_PATTERN.fullmatch(compact)
        if matched:
            metric_id = matched.group("metric_id")
            if metric_id not in set(metrics.values()):
                raise UnsupportedQuestionError("确认指标不在当前正式目录中。")
            start_date = _valid_date(matched.group("start_date"))
            end_date = _valid_date(matched.group("end_date"))
            if start_date >= end_date:
                raise UnsupportedQuestionError("增长排名的开始日期必须早于结束日期。")
            return GeneratedSQL(
                sql="""
                    WITH boundary_values AS (
                        SELECT institution_id,
                               MAX(CASE WHEN data_date = :start_date THEN metric_value_scaled END) AS start_value_scaled,
                               MAX(CASE WHEN data_date = :end_date THEN metric_value_scaled END) AS end_value_scaled
                        FROM metric_facts
                        WHERE metric_id = :metric_id
                          AND data_date IN (:start_date, :end_date)
                        GROUP BY institution_id
                    )
                    SELECT i.institution_name,
                           m.metric_name,
                           :end_date AS data_date,
                           scaled_value(b.end_value_scaled - b.start_value_scaled, m.value_scale) AS metric_value,
                           m.metric_unit
                    FROM boundary_values AS b
                    JOIN institutions AS i USING(institution_id)
                    JOIN metrics AS m ON m.metric_id = :metric_id
                    WHERE b.start_value_scaled IS NOT NULL
                      AND b.end_value_scaled IS NOT NULL
                    ORDER BY metric_value DESC, i.institution_id ASC
                """.strip(),
                parameters={
                    "metric_id": metric_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                generator_name=self.name,
                metadata=_metadata(
                    "排名",
                    "bar",
                    "metric_growth_ranking",
                    metric_id,
                    None,
                    {"start": start_date, "end": end_date},
                    comparison="absolute_change",
                ),
            )

        matched = SINGLE_PATTERN.fullmatch(compact)
        if matched:
            institution_id = _catalog_id(
                institutions, matched.group("institution"), "机构"
            )
            metric_id = _catalog_id(metrics, matched.group("metric"), "指标")
            data_date = _valid_date(matched.group("data_date"))
            return GeneratedSQL(
                sql="""
                    SELECT i.institution_name,
                           m.metric_name,
                           f.data_date,
                           scaled_value(f.metric_value_scaled, m.value_scale) AS metric_value,
                           m.metric_unit
                    FROM metric_facts AS f
                    JOIN institutions AS i USING(institution_id)
                    JOIN metrics AS m USING(metric_id)
                    WHERE f.institution_id = :institution_id
                      AND f.metric_id = :metric_id
                      AND f.data_date = :data_date
                """.strip(),
                parameters={
                    "institution_id": institution_id,
                    "metric_id": metric_id,
                    "data_date": data_date,
                },
                generator_name=self.name,
                metadata=_metadata(
                    "单值",
                    "none",
                    "metric_single_value",
                    metric_id,
                    institution_id,
                    {"start": data_date, "end": data_date},
                ),
            )

        matched = RANKING_PATTERN.fullmatch(compact)
        if matched:
            metric_id = _catalog_id(metrics, matched.group("metric"), "指标")
            data_date = _valid_date(matched.group("data_date"))
            return GeneratedSQL(
                sql="""
                    SELECT i.institution_name,
                           m.metric_name,
                           f.data_date,
                           scaled_value(f.metric_value_scaled, m.value_scale) AS metric_value,
                           m.metric_unit
                    FROM metric_facts AS f
                    JOIN institutions AS i USING(institution_id)
                    JOIN metrics AS m USING(metric_id)
                    WHERE f.metric_id = :metric_id
                      AND f.data_date = :data_date
                    ORDER BY metric_value DESC, i.institution_id ASC
                """.strip(),
                parameters={"metric_id": metric_id, "data_date": data_date},
                generator_name=self.name,
                metadata=_metadata(
                    "排名",
                    "bar",
                    "metric_ranking",
                    metric_id,
                    None,
                    {"start": data_date, "end": data_date},
                ),
            )

        matched = TREND_PATTERN.fullmatch(compact)
        if matched:
            institution_id = _catalog_id(
                institutions, matched.group("institution"), "机构"
            )
            metric_id = _catalog_id(metrics, matched.group("metric"), "指标")
            start_date = _valid_date(matched.group("start_date"))
            end_date = _valid_date(matched.group("end_date"))
            if start_date > end_date:
                raise UnsupportedQuestionError("趋势查询的开始日期不能晚于结束日期。")
            return GeneratedSQL(
                sql="""
                    SELECT i.institution_name,
                           m.metric_name,
                           f.data_date,
                           scaled_value(f.metric_value_scaled, m.value_scale) AS metric_value,
                           m.metric_unit
                    FROM metric_facts AS f
                    JOIN institutions AS i USING(institution_id)
                    JOIN metrics AS m USING(metric_id)
                    WHERE f.institution_id = :institution_id
                      AND f.metric_id = :metric_id
                      AND f.data_date BETWEEN :start_date AND :end_date
                    ORDER BY f.data_date ASC
                """.strip(),
                parameters={
                    "institution_id": institution_id,
                    "metric_id": metric_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                generator_name=self.name,
                metadata=_metadata(
                    "趋势",
                    "line",
                    "metric_trend",
                    metric_id,
                    institution_id,
                    {"start": start_date, "end": end_date},
                ),
            )

        raise RuleNotMatchedError(
            "该正式数据问题尚未配置确定性规则。可尝试单值、机构排名或趋势问题。"
        )


def _normalize(question: str) -> str:
    return "".join(question.strip().split()).rstrip("。？?")


def _valid_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise UnsupportedQuestionError("日期必须是有效的 YYYY-MM-DD 格式。") from exc


def _catalogs(context: QueryContext) -> tuple[dict[str, str], dict[str, str]]:
    try:
        metric_payload = yaml.safe_load(context.metric_context) or {}
        institution_payload = yaml.safe_load(context.institution_context) or {}
        metrics = {
            str(item["name"]): str(item["id"])
            for item in metric_payload.get("metrics", [])
        }
        institutions = {
            str(item["name"]): str(item["id"])
            for item in institution_payload.get("institutions", [])
        }
    except (TypeError, KeyError, yaml.YAMLError) as exc:
        raise ConfigurationError("正式业务目录格式不正确。") from exc
    if not metrics or not institutions:
        raise ConfigurationError("正式业务目录为空。")
    return metrics, institutions


def _catalog_id(catalog: dict[str, str], name: str, label: str) -> str:
    identifier = catalog.get(name)
    if identifier is None:
        raise UnsupportedQuestionError(f"{label}“{name}”不在当前正式目录中。")
    return identifier


def _metadata(
    result_type: str,
    chart_type: str,
    intent: str,
    metric_id: str,
    institution_id: str | None,
    time_range: dict[str, str],
    comparison: str | None = None,
) -> QueryMetadata:
    filters = {"institution_id": institution_id} if institution_id else {}
    return QueryMetadata(
        configured_mode="rule",
        executed_generator="rule",
        rule_matched=True,
        route="Rule",
        result_type=result_type,
        chart_type=chart_type,
        semantic=SemanticMetadata(
            intent=intent,
            business_domain="bank_operation",
            metrics=[metric_id],
            dimensions=["institution", "data_date"],
            filters=filters,
            time_range=time_range,
            confidence=1.0,
            comparison=comparison,
        ),
    )
