import unittest

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    SCORE_NOT_SCORED_SYSTEM_ERROR,
    EvalRecord,
)
from evaluation.reporting import summarize, to_public_markdown


def _record(
    question_id: str,
    partition: str,
    difficulty: str,
    score_status: str,
    route: str | None = "RULE",
    error_code: str | None = None,
    sql: str | None = "SELECT 1",
    elapsed_ms: int | None = 100,
    stage: str | None = None,
) -> EvalRecord:
    return EvalRecord(
        question_id=question_id,
        partition=partition,
        difficulty=difficulty,
        question_type="合成",
        run_id="run-1",
        started_at="2026-07-18T10:00:00",
        elapsed_ms=elapsed_ms,
        route=route,
        sql=sql,
        error_code=error_code,
        score_status=score_status,
        attribution_stage=stage,
    )


class SummarizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _record("TRAIN-S-01", "TRAIN", "S", SCORE_CORRECT, elapsed_ms=100),
            _record("TRAIN-S-02", "TRAIN", "S", SCORE_INCORRECT, elapsed_ms=200, stage="结果不一致"),
            _record(
                "TRAIN-M-01",
                "TRAIN",
                "M",
                SCORE_NOT_SCORED_SYSTEM_ERROR,
                route="LLM",
                error_code="QUERY_TIMEOUT",
                sql=None,
                elapsed_ms=400,
                stage="数据库执行",
            ),
            _record("VAL-S-01", "VAL", "S", SCORE_CORRECT, elapsed_ms=300),
        ]

    def test_totals_and_rates(self) -> None:
        summary = summarize(self.records)
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["by_partition"]["TRAIN"]["total"], 3)
        self.assertEqual(summary["score_counts"][SCORE_CORRECT], 2)
        self.assertAlmostEqual(summary["rates"]["sql_generated"], 3 / 4)
        self.assertAlmostEqual(summary["rates"]["no_error"], 3 / 4)
        self.assertAlmostEqual(summary["rates"]["end_to_end_correct"], 2 / 4)
        self.assertAlmostEqual(summary["rates"]["correct_among_scored"], 2 / 3)

    def test_latency_percentiles(self) -> None:
        summary = summarize(self.records)
        self.assertEqual(summary["latency_ms"]["p50"], 200)
        self.assertEqual(summary["latency_ms"]["p95"], 400)

    def test_failure_stages_counted(self) -> None:
        summary = summarize(self.records)
        self.assertEqual(summary["failure_stages"]["数据库执行"], 1)
        self.assertEqual(summary["failure_stages"]["结果不一致"], 1)

    def test_empty_records(self) -> None:
        summary = summarize([])
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["latency_ms"]["p50"])


class PublicMarkdownTest(unittest.TestCase):
    def test_contains_aggregates_only(self) -> None:
        summary = summarize(
            [_record("TRAIN-S-01", "TRAIN", "S", SCORE_CORRECT)]
        )
        markdown = to_public_markdown(summary, run_id="run-1")
        self.assertIn("run-1", markdown)
        self.assertIn("总题数", markdown)
        self.assertNotIn("TRAIN-S-01", markdown)
        self.assertNotIn("SELECT", markdown)


if __name__ == "__main__":
    unittest.main()
