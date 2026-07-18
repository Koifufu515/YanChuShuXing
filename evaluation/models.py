from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCORE_CORRECT = "CORRECT"
SCORE_INCORRECT = "INCORRECT"
SCORE_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
SCORE_EXCLUDED_ANOMALY = "EXCLUDED_ANOMALY"
SCORE_NOT_SCORED_SYSTEM_ERROR = "NOT_SCORED_SYSTEM_ERROR"

SCORE_STATUSES = frozenset(
    {
        SCORE_CORRECT,
        SCORE_INCORRECT,
        SCORE_NEEDS_MANUAL_REVIEW,
        SCORE_EXCLUDED_ANOMALY,
        SCORE_NOT_SCORED_SYSTEM_ERROR,
    }
)


@dataclass(frozen=True)
class EvalQuestion:
    question_id: str
    partition: str
    difficulty: str
    question_type: str
    question_text: str
    official_answer: str


@dataclass
class EvalRecord:
    question_id: str
    partition: str
    difficulty: str
    question_type: str
    run_id: str
    started_at: str
    elapsed_ms: int | None = None
    configured_mode: str | None = None
    executed_generator: str | None = None
    rule_matched: bool | None = None
    route: str | None = None
    semantic: dict[str, Any] | None = None
    sql: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    total_row_count: int = 0
    summary: str | None = None
    llm_latency_ms: float | None = None
    score_status: str = SCORE_NEEDS_MANUAL_REVIEW
    score_reason: str | None = None
    attribution_stage: str | None = None
    attribution_owner: str | None = None
    code_version: str | None = None
    model: str | None = None
    db_label: str | None = None
    rules_version: str | None = None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json_line(cls, line: str) -> "EvalRecord":
        payload = json.loads(line)
        return cls(**payload)
