from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.application.answer_models import (
    AnalysisFacts,
    AnswerPayload,
    AnswerTable,
    BenchmarkComparisonFacts,
    ChartSeries,
    ChartSpec,
    KeyMetric,
    MainMetricFact,
    MainMetricsOverviewFacts,
    TrendOverviewFacts,
)


class DeterministicAnswerComposer:
    """仅根据已经校验和执行的事实生成用户回答。"""

    def compose(
        self,
        question: str,
        query_plan: dict[str, Any],
        facts: AnalysisFacts,
    ) -> AnswerPayload:
        del question, query_plan
        if isinstance(
            facts,
            TrendOverviewFacts,
        ):
            return self._compose_trend(facts)

        if isinstance(
            facts,
            MainMetricsOverviewFacts,
        ):
            return self._compose_main_metrics(facts)

        if isinstance(
            facts,
            BenchmarkComparisonFacts,
        ):
            return self._compose_benchmark(facts)

        raise TypeError(
            f"暂不支持的分析事实类型："
            f"{type(facts).__name__}"
        )

    def _compose_main_metrics(
        self,
        facts: MainMetricsOverviewFacts,
    ) -> AnswerPayload:
        better = [
            metric
            for metric in facts.metrics
            if metric.performance_band == "better"
        ]
        worse = [
            metric
            for metric in facts.metrics
            if metric.performance_band == "worse"
        ]
        middle = [
            metric
            for metric in facts.metrics
            if metric.performance_band == "middle"
        ]
        boundary_ties = [
            metric
            for metric in facts.metrics
            if metric.performance_band
            == "boundary_tie"
        ]
        numeric_only = [
            metric
            for metric in facts.metrics
            if metric.performance_band
            == "numeric_only"
        ]

        summary_parts = [
            (
                f"截至 {self._display_period(facts.period)}，"
                f"{facts.subject.institution_name}共列示"
                f"{len(facts.metrics)}项主要经营指标。"
            )
        ]

        if better:
            summary_parts.append(
                "表现较好的指标为"
                + "、".join(
                    metric.metric_name
                    for metric in better
                )
                + "。"
            )
        else:
            summary_parts.append(
                "本期没有进入全省前3名的指标。"
            )

        if worse:
            summary_parts.append(
                "表现较差的指标为"
                + "、".join(
                    metric.metric_name
                    for metric in worse
                )
                + "。"
            )
        else:
            summary_parts.append(
                "本期没有进入全省后4名的指标。"
            )

        if middle:
            summary_parts.append(
                f"另有{len(middle)}项指标处于"
                "全省中间区间。"
            )

        if boundary_ties:
            summary_parts.append(
                "存在并列边界指标："
                + "、".join(
                    metric.metric_name
                    for metric in boundary_ties
                )
                + "。"
            )

        if numeric_only:
            summary_parts.append(
                "存贷比仅按数值降序排名，"
                "不作经营优劣判断。"
            )

        return AnswerPayload(
            answer_type=facts.answer_type,
            headline=(
                f"{facts.subject.institution_name}"
                "主要经营指标排名与表现概览"
            ),
            summary="".join(summary_parts),
            key_metrics=[
                KeyMetric(
                    label="主要经营指标",
                    value=len(facts.metrics),
                    unit="项",
                ),
                KeyMetric(
                    label="表现较好",
                    value=len(better),
                    unit="项",
                ),
                KeyMetric(
                    label="表现较差",
                    value=len(worse),
                    unit="项",
                ),
            ],
            table=AnswerTable(
                columns=[
                    "指标",
                    "数值",
                    "单位",
                    "全省排名",
                    "表现判断",
                ],
                rows=[
                    [
                        metric.metric_name,
                        self._display_number(
                            metric.value
                        ),
                        metric.unit,
                        f"第{metric.rank}名",
                        self._performance_text(
                            metric
                        ),
                    ]
                    for metric in facts.metrics
                ],
            ),
            chart_spec=None,
        )

    def _compose_benchmark(
        self,
        facts: BenchmarkComparisonFacts,
    ) -> AnswerPayload:
        target = self._display_number(
            facts.target_value
        )
        benchmark = self._display_number(
            facts.benchmark_value
        )
        difference = self._display_number(
            abs(Decimal(str(facts.difference)))
        )
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
                f"该行{position}{difference}"
                f"{difference_unit}。"
            )
        else:
            comparison = (
                f"该行{position}全省平均水平"
                f"{difference}{difference_unit}。"
            )

        assessment = self._assessment_text(
            facts
        )
        summary = (
            f"截至 {self._display_period(facts.period)}，"
            f"{facts.subject.institution_name}的"
            f"{facts.metric.metric_name}为"
            f"{target}{metric_unit}，"
            f"{facts.benchmark_name}为"
            f"{benchmark}{metric_unit}。"
            f"{comparison}{assessment}"
        )
        headline = (
            f"{facts.subject.institution_name}"
            f"{facts.metric.metric_name}"
            f"{position}全省均值"
            f"{difference}{difference_unit}"
            if facts.relative_position != "equal"
            else (
                f"{facts.subject.institution_name}"
                f"{facts.metric.metric_name}"
                "与全省均值持平"
            )
        )

        labels = [
            facts.subject.institution_name,
            facts.benchmark_name,
        ]
        values = [
            facts.target_value,
            facts.benchmark_value,
        ]

        return AnswerPayload(
            answer_type=facts.answer_type,
            headline=headline,
            summary=summary,
            key_metrics=[
                KeyMetric(
                    "目标机构",
                    facts.target_value,
                    metric_unit,
                ),
                KeyMetric(
                    "全省均值",
                    facts.benchmark_value,
                    metric_unit,
                ),
            ],
            table=AnswerTable(
                columns=[
                    "比较对象",
                    facts.metric.metric_name,
                    "单位",
                ],
                rows=[
                    [
                        facts.subject.institution_name,
                        facts.target_value,
                        metric_unit,
                    ],
                    [
                        facts.benchmark_name,
                        facts.benchmark_value,
                        metric_unit,
                    ],
                ],
            ),
            chart_spec=ChartSpec(
                chart_type="bar",
                title=(
                    f"{facts.metric.metric_name}对比"
                ),
                categories=labels,
                series=[
                    ChartSeries(
                        facts.metric.metric_name,
                        values,
                    )
                ],
                unit=metric_unit,
            ),
        )

    @staticmethod
    def _performance_text(
        metric: MainMetricFact,
    ) -> str:
        labels = {
            "better": "表现较好",
            "worse": "表现较差",
            "middle": "中间区间",
            "numeric_only": "仅数值排名",
            "boundary_tie": "并列边界",
        }
        label = labels.get(
            metric.performance_band,
            "暂不判断",
        )

        if metric.performance_direction is None:
            return label

        direction = (
            "高值表现更好"
            if metric.performance_direction
            == "higher_is_better"
            else "低值表现更好"
        )
        return f"{label}（{direction}）"

    def _compose_trend(
        self,
        facts: TrendOverviewFacts,
    ) -> AnswerPayload:
        if not facts.series:
            raise ValueError(
                "趋势事实至少需要一条时间序列。"
            )

        categories = sorted(
            {
                point.data_date
                for series in facts.series
                for point in series.points
            }
        )

        if not categories:
            raise ValueError(
                "趋势事实没有有效时间点。"
            )

        institution_names = {
            series.institution.institution_name
            for series in facts.series
        }
        metric_ids = {
            series.metric.metric_id
            for series in facts.series
        }
        units = {
            series.metric.unit
            for series in facts.series
        }

        chart_series: list[ChartSeries] = []
        long_table_rows: list[list[object]] = []

        for series in facts.series:
            points = sorted(
                series.points,
                key=lambda point: point.data_date,
            )
            point_map = {
                point.data_date: point.value
                for point in points
            }

            if (
                len(metric_ids) == 1
                and len(institution_names) > 1
            ):
                series_name = (
                    series.institution.institution_name
                )
            elif (
                len(institution_names) == 1
                and len(metric_ids) > 1
            ):
                series_name = series.metric.metric_name
            elif len(facts.series) == 1:
                series_name = series.metric.metric_name
            else:
                series_name = (
                    f"{series.institution.institution_name}"
                    f" · {series.metric.metric_name}"
                )

            chart_series.append(
                ChartSeries(
                    name=series_name,
                    values=[
                        point_map.get(data_date)
                        for data_date in categories
                    ],
                )
            )

            for point in points:
                long_table_rows.append(
                    [
                        series.institution.institution_name,
                        series.metric.metric_name,
                        point.data_date,
                        point.value,
                        series.metric.unit,
                    ]
                )

        if len(facts.series) == 1:
            series = facts.series[0]
            points = sorted(
                series.points,
                key=lambda point: point.data_date,
            )

            if not points:
                raise ValueError(
                    "趋势序列没有有效数据点。"
                )

            first_point = points[0]
            last_point = points[-1]

            first_value = Decimal(
                str(first_point.value)
            )
            last_value = Decimal(
                str(last_point.value)
            )
            change = last_value - first_value

            max_point = max(
                points,
                key=lambda point: Decimal(
                    str(point.value)
                ),
            )
            min_point = min(
                points,
                key=lambda point: Decimal(
                    str(point.value)
                ),
            )

            if change > 0:
                direction_word = "增加"
                headline_direction = "总体上升"
            elif change < 0:
                direction_word = "减少"
                headline_direction = "总体下降"
            else:
                direction_word = "保持不变"
                headline_direction = "总体持平"

            institution_name = (
                series.institution.institution_name
            )
            metric_name = series.metric.metric_name
            unit = series.metric.unit

            headline = (
                f"{institution_name}{metric_name}"
                f"{headline_direction}"
            )

            if change == 0:
                change_sentence = (
                    f"区间内保持不变，变化量为"
                    f"{self._display_number(change)}"
                    f"{unit}。"
                )
            else:
                change_sentence = (
                    f"累计{direction_word}"
                    f"{self._display_number(abs(change))}"
                    f"{unit}。"
                )

            summary = (
                f"{institution_name}的{metric_name}"
                f"从"
                f"{self._display_period(first_point.data_date)}"
                f"的"
                f"{self._display_number(first_point.value)}"
                f"{unit}变为"
                f"{self._display_period(last_point.data_date)}"
                f"的"
                f"{self._display_number(last_point.value)}"
                f"{unit}，"
                f"{change_sentence}"
            )

            key_metrics = []

            table = AnswerTable(
                columns=[
                    "日期",
                    metric_name,
                    "单位",
                ],
                rows=[
                    [
                        point.data_date,
                        point.value,
                        unit,
                    ]
                    for point in points
                ],
            )

            chart_title = (
                f"{institution_name}"
                f"{metric_name}趋势"
            )
        else:
            increasing = 0
            decreasing = 0
            unchanged = 0

            for series in facts.series:
                points = sorted(
                    series.points,
                    key=lambda point: point.data_date,
                )
                if len(points) < 2:
                    unchanged += 1
                    continue

                change = (
                    Decimal(str(points[-1].value))
                    - Decimal(str(points[0].value))
                )

                if change > 0:
                    increasing += 1
                elif change < 0:
                    decreasing += 1
                else:
                    unchanged += 1

            headline = (
                f"{len(facts.series)}条时间序列"
                f"趋势分析"
            )
            summary = (
                f"本次分析覆盖"
                f"{self._display_period(facts.start_date)}"
                f"至"
                f"{self._display_period(facts.end_date)}，"
                f"共包含{len(facts.series)}条时间序列。"
                f"其中{increasing}条总体上升，"
                f"{decreasing}条总体下降，"
                f"{unchanged}条总体持平或数据不足。"
            )

            key_metrics = []

            table = AnswerTable(
                columns=[
                    "机构",
                    "指标",
                    "日期",
                    "指标值",
                    "单位",
                ],
                rows=long_table_rows,
            )

            chart_title = "经营指标趋势对比"

        chart_spec = (
            ChartSpec(
                chart_type="line",
                title=chart_title,
                categories=categories,
                series=chart_series,
                unit=next(iter(units)),
            )
            if len(units) == 1
            else None
        )

        return AnswerPayload(
            answer_type=facts.answer_type,
            headline=headline,
            summary=summary,
            key_metrics=key_metrics,
            table=table,
            chart_spec=chart_spec,
        )

    @staticmethod
    def _assessment_text(
        facts: BenchmarkComparisonFacts,
    ) -> str:
        metric_name = facts.metric.metric_name

        if facts.performance_assessment == "equal":
            return (
                "该指标当前与全省平均表现相当。"
            )

        if (
            facts.metric.performance_direction
            == "lower_is_better"
        ):
            principle = (
                f"{metric_name}越低，通常表示单位"
                "营业收入对应的经营成本越少，"
                if metric_name == "成本收入比"
                else f"{metric_name}越低通常表现越好，"
            )
        else:
            principle = (
                f"{metric_name}越高通常表现越好，"
            )

        result = (
            "相对较好"
            if facts.performance_assessment == "better"
            else "相对较弱"
        )
        return f"{principle}因此该行当前表现{result}。"

    @staticmethod
    def _display_number(
        value: object,
    ) -> str:
        numeric = Decimal(str(value))
        return format(
            numeric.quantize(Decimal("0.01")),
            ".2f",
        )

    @staticmethod
    def _display_period(
        value: str,
    ) -> str:
        parts = value.split("-")
        if (
            len(parts) == 3
            and all(part.isdigit() for part in parts)
        ):
            return (
                f"{int(parts[0])} 年 "
                f"{int(parts[1])} 月 "
                f"{int(parts[2])} 日"
            )
        return value
