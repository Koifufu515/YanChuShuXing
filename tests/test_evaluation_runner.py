from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from evaluation.models import EvaluationPaths
from evaluation.runner import (
    build_summary,
    execute_batch,
    is_retryable_exception,
    load_questions,
    select_questions,
)


class FakePipeline:
    def __init__(self):
        self.calls = []

    def run(self, command):
        self.calls.append(command.question)
        metadata = SimpleNamespace(
            failure_reason=None,
            query_plan={
                "status": {"code": "executable"},
                "operations": [],
            },
            execution_trace=[],
            plan_repair_attempted=False,
        )
        return SimpleNamespace(
            request_id=command.request_id,
            question=command.question,
            columns=["value"],
            rows=[[1.23]],
            summary="结果为1.23。",
            warnings=[],
            error=None,
            metadata=metadata,
        )



class FlakyPipeline(FakePipeline):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def run(self, command):
        self.attempts += 1
        if self.attempts == 1:
            raise http.client.IncompleteRead(b"partial")
        return super().run(command)

def make_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "问题答案清单"
    sheet.append(
        [
            "问题编号",
            "问题类型",
            "问题难度",
            "问题描述",
            "问题结果",
            "更正后答案",
        ]
    )
    sheet.append(
        [
            "TRAIN-S-01",
            "单值",
            "简单",
            "第一道训练题",
            "旧答案",
            "更正答案",
        ]
    )
    sheet.append(
        [
            "TRAIN-S-02",
            "单值",
            "简单",
            "第二道训练题",
            "官方答案",
            None,
        ]
    )
    sheet.append(
        [
            "VAL-S-01",
            "单值",
            "简单",
            "验证题",
            "验证答案",
            None,
        ]
    )
    workbook.save(path)


class EvaluationRunnerTest(unittest.TestCase):
    def test_load_questions_prefers_corrected_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "questions.xlsx"
            make_workbook(source)

            questions = load_questions(source)
            train = select_questions(questions, "TRAIN")

            self.assertEqual(len(train), 2)
            self.assertEqual(
                train[0].expected_answer,
                "更正答案",
            )
            self.assertEqual(
                train[0].answer_source,
                "corrected",
            )
            self.assertEqual(
                train[1].expected_answer,
                "官方答案",
            )
            self.assertEqual(
                train[1].answer_source,
                "official",
            )

    def test_execute_batch_saves_and_resumes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "questions.xlsx"
            make_workbook(source)
            questions = select_questions(
                load_questions(source),
                "TRAIN",
            )
            paths = EvaluationPaths(
                project_root=root,
                source=source,
                run_root=root / "runs" / "train-smoke",
            )
            manifest = {
                "run_id": "train-smoke",
                "split": "TRAIN",
                "source": {"sha256": "source"},
                "system": {
                    "code_commit": "commit",
                    "prompt_sha256": "prompt",
                    "schema_sha256": "schema",
                    "context_sha256": "context",
                },
                "database": {
                    "run_id": "database",
                    "source_sha256": "database-source",
                },
            }
            pipeline = FakePipeline()

            command_factory = (
                lambda question, run_id, question_id, attempt: SimpleNamespace(
                    question=question,
                    user_id="batch_evaluation",
                    conversation_id=run_id,
                    request_id=f"{question_id}-{attempt}",
                )
            )
            first = execute_batch(
                pipeline,
                questions,
                paths,
                manifest,
                command_factory=command_factory,
            )
            second = execute_batch(
                pipeline,
                questions,
                paths,
                manifest,
                command_factory=command_factory,
            )

            self.assertEqual(len(pipeline.calls), 2)
            self.assertEqual(first["completed_total"], 2)
            self.assertEqual(second["skipped_this_invocation"], 2)
            self.assertTrue(paths.manifest.is_file())
            self.assertTrue(paths.results.is_file())
            self.assertTrue(paths.summary.is_file())
            self.assertTrue(paths.failures.is_file())

            result_lines = [
                json.loads(line)
                for line in paths.results.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]
            self.assertEqual(len(result_lines), 2)
            self.assertTrue(
                all(
                    item["comparison_status"] == "not_scored"
                    for item in result_lines
                )
            )

    def test_incomplete_read_is_retryable(self):
        self.assertTrue(
            is_retryable_exception(
                http.client.IncompleteRead(b"partial")
            )
        )

    def test_execute_batch_retries_transient_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "questions.xlsx"
            make_workbook(source)
            questions = select_questions(
                load_questions(source),
                "TRAIN",
                limit=1,
            )
            paths = EvaluationPaths(
                project_root=root,
                source=source,
                run_root=root / "runs" / "retry-test",
            )
            manifest = {
                "run_id": "retry-test",
                "split": "TRAIN",
                "source": {"sha256": "source"},
                "system": {
                    "code_commit": "commit",
                    "prompt_sha256": "prompt",
                    "schema_sha256": "schema",
                    "context_sha256": "context",
                },
                "database": {
                    "run_id": "database",
                    "source_sha256": "database-source",
                },
            }
            pipeline = FlakyPipeline()
            command_factory = (
                lambda question, run_id, question_id, attempt: SimpleNamespace(
                    question=question,
                    user_id="batch_evaluation",
                    conversation_id=run_id,
                    request_id=f"{question_id}-{attempt}",
                )
            )

            summary = execute_batch(
                pipeline,
                questions,
                paths,
                manifest,
                retries=1,
                command_factory=command_factory,
            )

            self.assertEqual(pipeline.attempts, 2)
            self.assertEqual(summary["run_status_counts"], {"success": 1})
            record = json.loads(
                paths.results.read_text(encoding="utf-8").strip()
            )
            self.assertEqual(record["attempt_count"], 2)

    def test_build_summary_counts_statuses(self):
        summary = build_summary(
            selected_questions=[],
            records=[
                {
                    "run_status": "success",
                    "duration_ms": 100,
                    "plan_repair_attempted": False,
                },
                {
                    "run_status": "failed",
                    "duration_ms": 300,
                    "error": {"code": "QUERY_EXECUTION_ERROR"},
                    "plan_repair_attempted": True,
                },
            ],
            skipped=0,
            executed=2,
            interrupted=False,
        )

        self.assertEqual(
            summary["run_status_counts"],
            {"failed": 1, "success": 1},
        )
        self.assertEqual(
            summary["error_code_counts"],
            {"QUERY_EXECUTION_ERROR": 1},
        )
        self.assertEqual(
            summary["plan_repair_attempted_total"],
            1,
        )
        self.assertEqual(summary["duration_ms"]["p50"], 200.0)


if __name__ == "__main__":
    unittest.main()
