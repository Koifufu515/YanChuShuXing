from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.application.answer_models import (
    AnswerPayload,
    AnswerTable,
    BenchmarkComparisonFacts,
    ChartSeries,
    ChartSpec,
    KeyMetric,
)


class DeterministicAnswerComposer:
    """Compose user-facing answers exclusively from verified execution facts."""

    def compose(
        self,
        question: str,
        query_plan: dict[str, Any],
        facts: BenchmarkComparisonFacts,
    ) -> AnswerPayload:
        del question, query_plan
        target = self._display_number(facts.target_value)
        benchmark = self._display_number(facts.benchmark_value)
        difference = self._display_number(abs(Decimal(str(facts.difference))))
        difference_unit = (
            "个百分点"
            if facts.difference_unit == "百分点"
            else facts.difference_unit
        )
        metric_unit = facts.metric.unit
        position = {
            "above": "高于",
            "below": "低于",
            "equal": "与全省平均水平相同，差异为",
        }[facts.relative_position]
        if facts.relative_position == "equal":
            comparison = (
                f"该行{position}{difference}{difference_unit}。"
            )
        else:
            comparison = (
                f"该行{position}全省平均水平{difference}{difference_unit}。"
            )
        assessment = self._assessment_text(facts)
        summary = (
            f"截至 {self._display_period(facts.period)}，{facts.subject.institution_name}的"
            f"{facts.metric.metric_name}为{target}{metric_unit}，"
            f"{facts.benchmark_name}为{benchmark}{metric_unit}。"
            f"{comparison}{assessment}"
        )
        headline = (
            f"{facts.subject.institution_name}{facts.metric.metric_name}"
            f"{position}全省均值{difference}{difference_unit}"
            if facts.relative_position != "equal"
            else f"{facts.subject.institution_name}{facts.metric.metric_name}与全省均值持平"
        )
        labels = [facts.subject.institution_name, facts.benchmark_name]
        values = [facts.target_value, facts.benchmark_value]
        return AnswerPayload(
            answer_type=facts.answer_type,
            headline=headline,
            summary=summary,
            key_metrics=[
                KeyMetric("目标机构", facts.target_value, metric_unit),
                KeyMetric("全省均值", facts.benchmark_value, metric_unit),
            ],
            table=AnswerTable(
                columns=["比较对象", facts.metric.metric_name, "单位"],
                rows=[
                    [facts.subject.institution_name, facts.target_value, metric_unit],
                    [facts.benchmark_name, facts.benchmark_value, metric_unit],
                ],
            ),
            chart_spec=ChartSpec(
                chart_type="bar",
                title=f"{facts.metric.metric_name}对比",
                categories=labels,
                series=[ChartSeries(facts.metric.metric_name, values)],
                unit=metric_unit,
            ),
        )

    @staticmethod
    def _assessment_text(facts: BenchmarkComparisonFacts) -> str:
        metric_name = facts.metric.metric_name
        if facts.performance_assessment == "equal":
            return "该指标当前与全省平均表现相当。"
        if facts.metric.performance_direction == "lower_is_better":
            principle = f"{metric_name}越低，通常表示单位营业收入对应的经营成本越少，" if metric_name == "成本收入比" else f"{metric_name}越低通常表现越好，"
        else:
            principle = f"{metric_name}越高通常表现越好，"
        result = "相对较好" if facts.performance_assessment == "better" else "相对较弱"
        return f"{principle}因此该行当前表现{result}。"

    @staticmethod
    def _display_number(value: object) -> str:
        numeric = Decimal(str(value))
        return format(numeric.quantize(Decimal("0.01")), ".2f")

    @staticmethod
    def _display_period(value: str) -> str:
        parts = value.split("-")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            return f"{int(parts[0])} 年 {int(parts[1])} 月 {int(parts[2])} 日"
        return value
