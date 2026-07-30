from __future__ import annotations

from dataclasses import dataclass, field


JsonScalar = str | int | float | bool | None


@dataclass(frozen=True)
class InstitutionRef:
    institution_id: str | None
    institution_name: str


@dataclass(frozen=True)
class MetricRef:
    metric_id: str
    metric_name: str
    unit: str
    performance_direction: str


@dataclass(frozen=True)
class BenchmarkComparisonFacts:
    subject: InstitutionRef
    metric: MetricRef
    period: str
    target_value: JsonScalar
    benchmark_name: str
    benchmark_value: JsonScalar
    difference: JsonScalar
    difference_unit: str
    relative_position: str
    performance_assessment: str
    answer_type: str = "benchmark_comparison"


@dataclass(frozen=True)
class MainMetricFact:
    metric_id: str
    metric_name: str
    value: JsonScalar
    unit: str
    rank: int
    performance_direction: str | None
    performance_band: str


@dataclass(frozen=True)
class MainMetricsOverviewFacts:
    subject: InstitutionRef
    period: str
    metrics: list[MainMetricFact]
    answer_type: str = "main_metrics_overview"


@dataclass(frozen=True)
class TrendPoint:
    data_date: str
    value: JsonScalar


@dataclass(frozen=True)
class TrendSeries:
    institution: InstitutionRef
    metric: MetricRef
    points: list[TrendPoint]


@dataclass(frozen=True)
class TrendOverviewFacts:
    start_date: str
    end_date: str
    grain: str
    series: list[TrendSeries]
    answer_type: str = "trend"


@dataclass(frozen=True)
class RankingItem:
    institution: InstitutionRef
    value: JsonScalar
    rank: int


@dataclass(frozen=True)
class MetricRankingFacts:
    metric: MetricRef
    items: list[RankingItem]
    population_size: int
    ranking_method: str


@dataclass(frozen=True)
class RankingOverviewFacts:
    period: str
    rankings: list[MetricRankingFacts]
    selection_mode: str
    requested_n: int | None = None
    answer_type: str = "ranking"


@dataclass(frozen=True)
class DirectMetricValueFact:
    metric_id: str
    metric_name: str
    value: JsonScalar
    unit: str


@dataclass(frozen=True)
class DirectMetricValuesFacts:
    subject: InstitutionRef
    period: str
    metrics: list[DirectMetricValueFact]
    answer_type: str = "direct_metric_values"


AnalysisFacts = (
    BenchmarkComparisonFacts
    | MainMetricsOverviewFacts
    | TrendOverviewFacts
    | RankingOverviewFacts
    | DirectMetricValuesFacts
)


@dataclass(frozen=True)
class KeyMetric:
    label: str
    value: JsonScalar
    unit: str | None = None


@dataclass(frozen=True)
class AnswerTable:
    columns: list[str]
    rows: list[list[JsonScalar]]


@dataclass(frozen=True)
class ChartSeries:
    name: str
    values: list[JsonScalar]


@dataclass(frozen=True)
class ChartSpec:
    chart_type: str
    title: str
    categories: list[str]
    series: list[ChartSeries]
    unit: str | None = None


@dataclass(frozen=True)
class AnswerPayload:
    answer_type: str
    headline: str
    summary: str
    key_metrics: list[KeyMetric] = field(
        default_factory=list
    )
    table: AnswerTable | None = None
    chart_spec: ChartSpec | None = None
