import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from evaluation.models import EvalQuestion, EvalRecord
from evaluation.runner import EvaluationRunner, RunContext


@dataclass
class FakeResult:
    payload: dict
    elapsed_ms: int = 50


class FakeClient:
    def __init__(self, payloads: dict[str, dict | Exception]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def query(self, question: str, user_id: str = "", conversation_id: str = "") -> FakeResult:
        self.calls.append(question)
        outcome = self.payloads[question]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResult(payload=outcome)


def _question(question_id: str, text: str) -> EvalQuestion:
    partition, difficulty, _ = question_id.split("-")
    return EvalQuestion(
        question_id=question_id,
        partition=partition,
        difficulty=difficulty,
        question_type="合成",
        question_text=text,
        official_answer="净利润为300元",
    )


def _ok_payload(sql: str = "SELECT 1") -> dict:
    return {
        "request_id": "req_x",
        "question": "q",
        "sql": sql,
        "columns": ["metric"],
        "rows": [["净利润", 300]],
        "summary": "净利润为300元",
        "warnings": [],
        "error": None,
        "metadata": {
            "configured_mode": "hybrid",
            "executed_generator": "rule",
            "rule_matched": True,
            "route": "RULE",
            "failure_reason": None,
            "provider": None,
            "model": None,
            "llm_latency_ms": None,
            "semantic": None,
            "fallback": {"used": False, "reason": None, "fallback_generator": None},
        },
    }


def _error_payload(code: str) -> dict:
    payload = _ok_payload(sql=None)
    payload["rows"] = []
    payload["summary"] = None
    payload["error"] = {"code": code, "message": "结构化错误", "retryable": False}
    return payload


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.context = RunContext(
            run_id="run-t",
            data_dir=self.data_dir,
            code_version="abc1234",
            model="deepseek-v4-flash",
            db_label="demo",
            configured_mode_label="hybrid",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _details_path(self) -> Path:
        return self.data_dir / "runs" / "run-t" / "details.jsonl"

    def test_writes_details_summary_and_scores(self) -> None:
        questions = [_question("TRAIN-S-01", "问一"), _question("TRAIN-S-02", "问二")]
        client = FakeClient({"问一": _ok_payload(), "问二": _error_payload("QUERY_TIMEOUT")})
        runner = EvaluationRunner(client, self.context)

        summary = runner.run(questions)

        lines = self._details_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        first = EvalRecord.from_json_line(lines[0])
        self.assertEqual(first.question_id, "TRAIN-S-01")
        self.assertEqual(first.score_status, "CORRECT")
        self.assertEqual(first.code_version, "abc1234")
        second = EvalRecord.from_json_line(lines[1])
        self.assertEqual(second.error_code, "QUERY_TIMEOUT")
        self.assertEqual(second.attribution_stage, "数据库执行")
        self.assertEqual(summary["total"], 2)
        summary_path = self.data_dir / "runs" / "run-t" / "summary.json"
        self.assertTrue(summary_path.is_file())
        self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["total"], 2)

    def test_resume_skips_completed_questions(self) -> None:
        questions = [_question("TRAIN-S-01", "问一"), _question("TRAIN-S-02", "问二")]
        client_first = FakeClient({"问一": _ok_payload(), "问二": _ok_payload()})
        EvaluationRunner(client_first, self.context).run([questions[0]])

        client_second = FakeClient({"问一": _ok_payload(), "问二": _ok_payload()})
        EvaluationRunner(client_second, self.context).run(questions)

        self.assertEqual(client_second.calls, ["问二"])
        lines = self._details_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_aborts_after_consecutive_connection_failures(self) -> None:
        questions = [
            _question("TRAIN-S-01", "问一"),
            _question("TRAIN-S-02", "问二"),
            _question("TRAIN-S-03", "问三"),
            _question("TRAIN-S-04", "问四"),
        ]
        client = FakeClient(
            {
                "问一": RuntimeError("连接失败"),
                "问二": RuntimeError("连接失败"),
                "问三": RuntimeError("连接失败"),
                "问四": _ok_payload(),
            }
        )
        runner = EvaluationRunner(client, self.context)
        with self.assertRaises(RuntimeError):
            runner.run(questions)
        lines = self._details_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        record = EvalRecord.from_json_line(lines[0])
        self.assertEqual(record.error_code, "API_CONNECTION_ERROR")
        self.assertEqual(record.attribution_stage, "评测环境")

    def test_rows_truncated_to_stored_limit(self) -> None:
        payload = _ok_payload()
        payload["rows"] = [["行", index] for index in range(80)]
        client = FakeClient({"问一": payload})
        runner = EvaluationRunner(client, self.context, max_stored_rows=50)
        runner.run([_question("TRAIN-S-01", "问一")])
        record = EvalRecord.from_json_line(
            self._details_path().read_text(encoding="utf-8").strip()
        )
        self.assertEqual(len(record.rows), 50)
        self.assertEqual(record.total_row_count, 80)


if __name__ == "__main__":
    unittest.main()
