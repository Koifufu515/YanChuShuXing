from __future__ import annotations

from dataclasses import dataclass, field


JsonScalar = str | int | float | bool | None


@dataclass(frozen=True)
class QueryCommand:
    question: str
    user_id: str
    conversation_id: str | None
    request_id: str


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class QueryContext:
    schema_context: str
    metric_context: str
    allowed_tables: frozenset[str]
    denied_columns: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SemanticMetadata:
    intent: str
    business_domain: str
    metrics: list[str]
    dimensions: list[str]
    filters: dict[str, JsonScalar]
    time_range: dict[str, JsonScalar] | None
    confidence: float | None = None


@dataclass(frozen=True)
class FallbackMetadata:
    used: bool = False
    reason: str | None = None
    fallback_generator: str | None = None


@dataclass(frozen=True)
class QueryMetadata:
    configured_mode: str
    executed_generator: str
    rule_matched: bool = False
    route: str | None = None
    failure_reason: str | None = None
    provider: str | None = None
    model: str | None = None
    llm_latency_ms: float | None = None
    semantic: SemanticMetadata | None = None
    fallback: FallbackMetadata = field(default_factory=FallbackMetadata)


@dataclass(frozen=True)
class GeneratedSQL:
    sql: str
    parameters: dict[str, JsonScalar] = field(default_factory=dict)
    generator_name: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    metadata: QueryMetadata | None = None


@dataclass(frozen=True)
class UserContext:
    user_id: str
    allowed_tables: frozenset[str]
    denied_columns: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SafetyResult:
    allowed: bool
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    referenced_tables: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[JsonScalar]]
    row_count: int
    truncated: bool
    duration_ms: float


@dataclass(frozen=True)
class FormattedResult:
    summary: str | None
    chart_hint: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueryOutcome:
    request_id: str
    question: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[JsonScalar]] = field(default_factory=list)
    summary: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: ErrorDetail | None = None
    metadata: QueryMetadata | None = None


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    temperature: float = 0.0
    timeout_seconds: float = 20.0
    response_format: str | None = "json_object"


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    latency_ms: float


@dataclass(frozen=True)
class BusinessSemantic:
    intent: str
    business_domain: str
    metrics: list[str]
    dimensions: list[str]
    filters: dict[str, JsonScalar]
    time_range: dict[str, JsonScalar] | None
    sort: list[dict[str, JsonScalar]]
    limit: int | None
    clarification_required: bool
    clarification_question: str | None
    confidence: float | None = None


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    request_id: str
    user_id: str
    question: str
    sql: str | None = None
    error_code: str | None = None
