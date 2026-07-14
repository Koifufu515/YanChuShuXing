from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.application.models import QueryOutcome


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
        )
