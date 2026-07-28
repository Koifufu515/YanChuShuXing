from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.application.answer_models import (
    AnswerPayload,
    AnswerTable,
    ChartSeries,
    ChartSpec,
    KeyMetric,
)
from app.application.models import JsonScalar, QueryOutcome


class QueryRequestDTO(BaseModel):
    question: str
    user_id: str = Field(min_length=1, max_length=64)
    conversation_id: str | None = Field(default=None, max_length=128)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized_length = len(value.strip())
        if not 2 <= normalized_length <= 500:
            raise ValueError("question 去除首尾空格后必须为2到500个字符")
        return value


class ErrorDTO(BaseModel):
    code: str
    message: str
    retryable: bool


class KeyMetricDTO(BaseModel):
    label: str
    value: JsonScalar
    unit: str | None = None

    @classmethod
    def from_model(cls, value: KeyMetric) -> "KeyMetricDTO":
        return cls(label=value.label, value=value.value, unit=value.unit)


class AnswerTableDTO(BaseModel):
    columns: list[str]
    rows: list[list[JsonScalar]]

    @classmethod
    def from_model(cls, value: AnswerTable) -> "AnswerTableDTO":
        return cls(columns=value.columns, rows=value.rows)


class ChartSeriesDTO(BaseModel):
    name: str
    values: list[JsonScalar]

    @classmethod
    def from_model(cls, value: ChartSeries) -> "ChartSeriesDTO":
        return cls(name=value.name, values=value.values)


class ChartSpecDTO(BaseModel):
    chart_type: str
    title: str
    categories: list[str]
    series: list[ChartSeriesDTO]
    unit: str | None = None

    @classmethod
    def from_model(cls, value: ChartSpec) -> "ChartSpecDTO":
        return cls(
            chart_type=value.chart_type,
            title=value.title,
            categories=value.categories,
            series=[ChartSeriesDTO.from_model(item) for item in value.series],
            unit=value.unit,
        )


class AnswerPayloadDTO(BaseModel):
    answer_type: str
    headline: str
    summary: str
    key_metrics: list[KeyMetricDTO]
    table: AnswerTableDTO | None = None
    chart_spec: ChartSpecDTO | None = None

    @classmethod
    def from_model(cls, value: AnswerPayload) -> "AnswerPayloadDTO":
        return cls(
            answer_type=value.answer_type,
            headline=value.headline,
            summary=value.summary,
            key_metrics=[KeyMetricDTO.from_model(item) for item in value.key_metrics],
            table=AnswerTableDTO.from_model(value.table) if value.table else None,
            chart_spec=(
                ChartSpecDTO.from_model(value.chart_spec)
                if value.chart_spec
                else None
            ),
        )


class QueryResponseDTO(BaseModel):
    request_id: str
    question: str
    sql: str | None
    columns: list[str]
    rows: list[list[Any]]
    summary: str | None
    warnings: list[str]
    error: ErrorDTO | None
    metadata: dict[str, Any] | None = None
    answer: AnswerPayloadDTO | None = None

    @classmethod
    def from_outcome(cls, outcome: QueryOutcome) -> "QueryResponseDTO":
        error = ErrorDTO(**outcome.error.__dict__) if outcome.error else None
        return cls(
            request_id=outcome.request_id,
            question=outcome.question,
            sql=outcome.sql,
            columns=outcome.columns,
            rows=outcome.rows,
            summary=outcome.summary,
            warnings=outcome.warnings,
            error=error,
            metadata=asdict(outcome.metadata) if outcome.metadata else None,
            answer=(
                AnswerPayloadDTO.from_model(outcome.answer)
                if outcome.answer
                else None
            ),
        )
