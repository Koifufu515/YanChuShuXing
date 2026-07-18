from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from evaluation.attribution import attribute
from evaluation.models import EvalQuestion, EvalRecord
from evaluation.normalization import RULES_VERSION as NORM_RULES_VERSION
from evaluation.reporting import summarize
from evaluation.scoring import RULES_VERSION as SCORE_RULES_VERSION, score


class QueryClient(Protocol):
    def query(self, question: str, user_id: str = ..., conversation_id: str = ...) -> Any: ...


@dataclass(frozen=True)
class RunContext:
    run_id: str
    data_dir: Path
    code_version: str | None = None
    model: str | None = None
    db_label: str | None = None
    configured_mode_label: str | None = None


class EvaluationRunner:
    def __init__(
        self,
        client: QueryClient,
        context: RunContext,
        *,
        max_consecutive_connection_failures: int = 3,
        max_stored_rows: int = 50,
    ) -> None:
        self.client = client
        self.context = context
        self.max_consecutive_connection_failures = max_consecutive_connection_failures
        self.max_stored_rows = max_stored_rows

    def run(
        self,
        questions: list[EvalQuestion],
        anomaly_ids: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        run_dir = Path(self.context.data_dir) / "runs" / self.context.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        details_path = run_dir / "details.jsonl"
        completed = self._load_completed_ids(details_path)

        consecutive_failures = 0
        with details_path.open("a", encoding="utf-8", newline="\n") as handle:
            for question in questions:
                if question.question_id in completed:
                    continue
                record = self._execute_one(question, anomaly_ids)
                handle.write(record.to_json_line() + "\n")
                handle.flush()
                if record.error_code == "API_CONNECTION_ERROR":
                    consecutive_failures += 1
                    if consecutive_failures >= self.max_consecutive_connection_failures:
                        raise RuntimeError(
                            f"连续 {consecutive_failures} 次无法连接后端，评测中止；"
                            f"已完成记录保留在 {details_path}，可修复后续跑。"
                        )
                else:
                    consecutive_failures = 0

        records = self._load_records(details_path)
        summary = summarize(records)
        summary["run_id"] = self.context.run_id
        summary["code_version"] = self.context.code_version
        summary["model"] = self.context.model
        summary["db_label"] = self.context.db_label
        summary["configured_mode_label"] = self.context.configured_mode_label
        summary["rules_version"] = self._rules_version()
        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary

    def _execute_one(
        self, question: EvalQuestion, anomaly_ids: frozenset[str]
    ) -> EvalRecord:
        record = EvalRecord(
            question_id=question.question_id,
            partition=question.partition,
            difficulty=question.difficulty,
            question_type=question.question_type,
            run_id=self.context.run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            code_version=self.context.code_version,
            model=self.context.model,
            db_label=self.context.db_label,
            rules_version=self._rules_version(),
        )
        try:
            result = self.client.query(
                question.question_text,
                user_id="evaluation",
                conversation_id=self.context.run_id,
            )
        except Exception as exc:
            record.error_code = "API_CONNECTION_ERROR"
            record.error_message = f"{type(exc).__name__}"
            record.score_status = "NOT_SCORED_SYSTEM_ERROR"
            record.score_reason = "后端连接失败，未获得响应。"
        else:
            payload = result.payload
            record.elapsed_ms = result.elapsed_ms
            record.sql = payload.get("sql")
            record.columns = payload.get("columns") or []
            rows = payload.get("rows") or []
            record.total_row_count = len(rows)
            record.rows = rows[: self.max_stored_rows]
            record.summary = payload.get("summary")
            error = payload.get("error")
            if error:
                record.error_code = error.get("code")
                record.error_message = error.get("message")
            metadata = payload.get("metadata") or {}
            record.configured_mode = metadata.get("configured_mode")
            record.executed_generator = metadata.get("executed_generator")
            record.rule_matched = metadata.get("rule_matched")
            record.route = metadata.get("route")
            record.semantic = metadata.get("semantic")
            record.llm_latency_ms = metadata.get("llm_latency_ms")
            score_result = score(
                question,
                summary=record.summary,
                rows=rows,
                error_code=record.error_code,
                anomaly_ids=anomaly_ids,
            )
            record.score_status = score_result.status
            record.score_reason = score_result.reason

        attribution = attribute(record.error_code, record.score_status)
        if attribution:
            record.attribution_stage = attribution.stage
            record.attribution_owner = attribution.owner
        return record

    @staticmethod
    def _rules_version() -> str:
        return f"{NORM_RULES_VERSION}+{SCORE_RULES_VERSION}"

    @staticmethod
    def _load_completed_ids(details_path: Path) -> set[str]:
        if not details_path.is_file():
            return set()
        completed: set[str] = set()
        with details_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    completed.add(json.loads(line)["question_id"])
        return completed

    @staticmethod
    def _load_records(details_path: Path) -> list[EvalRecord]:
        records: list[EvalRecord] = []
        with details_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(EvalRecord.from_json_line(line))
        return records
