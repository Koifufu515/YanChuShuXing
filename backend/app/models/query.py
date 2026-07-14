from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisType(str, Enum):
    LOOKUP = "lookup"
    AGGREGATION = "aggregation"
    RANKING = "ranking"
    TREND = "trend"
    COMPARISON = "comparison"
    CONTRIBUTION = "contribution"
    ANOMALY = "anomaly"


class TimeRange(BaseModel):
    start: str | None = None
    end: str | None = None
    label: str | None = None
    grain: Literal["day", "week", "month", "quarter", "year"] | None = None


class FilterCondition(BaseModel):
    field: str
    operator: Literal["=", "!=", ">", ">=", "<", "<=", "in", "between", "like"]
    value: Any


class QueryIntent(BaseModel):
    normalized_question: str
    analysis_type: AnalysisType
    metric_ids: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    time_range: TimeRange | None = None
    filters: list[FilterCondition] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=1000)
    ambiguity: list[str] = Field(default_factory=list)


class SchemaCandidate(BaseModel):
    object_name: str
    object_type: Literal["table", "column", "metric", "join_path"]
    score: float = Field(ge=0, le=1)
    reason: str


class QueryPlan(BaseModel):
    fact_tables: list[str]
    dimension_tables: list[str] = Field(default_factory=list)
    join_paths: list[str] = Field(default_factory=list)
    target_grain: str
    aggregation_steps: list[str]
    required_columns: list[str]
    assumptions: list[str] = Field(default_factory=list)


class GeneratedQuery(BaseModel):
    sql: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    dialect: str = "sqlite"
    cited_metrics: list[str]
    cited_schema: list[str]


class SafetyFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class SafetyReport(BaseModel):
    allowed: bool
    findings: list[SafetyFinding] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)


class QueryEvidence(BaseModel):
    evidence_id: str
    statement: str
    value: float | int | str | None
    source_columns: list[str]


class QueryResponse(BaseModel):
    question: str
    intent: QueryIntent
    plan: QueryPlan
    generated_query: GeneratedQuery
    safety: SafetyReport
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart_spec: dict[str, Any] | None = None
    evidence: list[QueryEvidence] = Field(default_factory=list)
    explanation: str | None = None
    follow_up_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    user_role: str = "analyst"
    branch_scope: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
