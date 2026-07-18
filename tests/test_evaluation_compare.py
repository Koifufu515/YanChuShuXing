import tempfile
import unittest
from pathlib import Path

from evaluation.compare import compare_runs, load_run_records, to_markdown
from evaluation.models import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    EvalRecord,
)


def _record(
    question_id: str,
    score_status: str,
    error_code: str | None = None,
    elapsed_ms: int = 100,
    run_id: str = "run",
) -> EvalRecord:
    return EvalRecord(
        question_id=question_id,
        partition="TRAIN",
        difficulty="S",
        question_type="合成",
        run_id=run_id,
        started_at="t",
        elapsed_ms=elapsed_ms,
        error_code=error_code,
        score_status=score_status,
    )


def _write_run(root: Path, run_id: str, records: list[EvalRecord]) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    with (run_dir / "details.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.to_json_line() + "\n")


class CompareRunsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        _write_run(
            self.root,
            "old",
            [
                _record("TRAIN-S-01", SCORE_INCORRECT, run_id="old"),
                _record("TRAIN-S-02", SCORE_CORRECT, run_id="old", elapsed_ms=100),
                _record("TRAIN-S-03", SCORE_CORRECT, run_id="old"),
            ],
        )
        _write_run(
            self.root,
            "new",
            [
                _record("TRAIN-S-01", SCORE_CORRECT, run_id="new"),
                _record("TRAIN-S-02", SCORE_INCORRECT, run_id="new", elapsed_ms=300),
                _record(
                    "TRAIN-S-03",
                    "NOT_SCORED_SYSTEM_ERROR",
                    error_code="QUERY_TIMEOUT",
                    run_id="new",
                ),
            ],
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_improved_regressed_and_new_errors(self) -> None:
        old = load_run_records(self.root, "old")
        new = load_run_records(self.root, "new")
        result = compare_runs(old, new)
        self.assertEqual(result["improved"], ["TRAIN-S-01"])
        self.assertEqual(sorted(result["regressed"]), ["TRAIN-S-02", "TRAIN-S-03"])
        self.assertEqual(result["new_errors"], ["TRAIN-S-03"])
        self.assertAlmostEqual(result["correct_rate_delta"], (1 / 3) - (2 / 3))

    def test_markdown_contains_ids_but_no_question_text(self) -> None:
        old = load_run_records(self.root, "old")
        new = load_run_records(self.root, "new")
        markdown = to_markdown(compare_runs(old, new), old_run_id="old", new_run_id="new")
        self.assertIn("TRAIN-S-01", markdown)
        self.assertIn("退化", markdown)

    def test_markdown_shows_set_difference_and_handles_missing_latency(self) -> None:
        old = load_run_records(self.root, "old")
        new = load_run_records(self.root, "new")
        result = compare_runs(old, new)
        result["only_in_old"] = ["TRAIN-S-09"]
        result["mean_latency_delta_ms"] = None
        markdown = to_markdown(result, old_run_id="old", new_run_id="new")
        self.assertIn("仅旧版有：1", markdown)
        self.assertIn("仅新版有：0", markdown)
        self.assertIn("N/A", markdown)
        self.assertNotIn("None ms", markdown)

    def test_grouped_rate_delta_and_latency_percentiles(self) -> None:
        old = load_run_records(self.root, "old")
        new = load_run_records(self.root, "new")
        result = compare_runs(old, new)
        self.assertAlmostEqual(
            result["rate_delta_by_partition"]["TRAIN"], (1 / 3) - (2 / 3)
        )
        self.assertAlmostEqual(
            result["rate_delta_by_difficulty"]["S"], (1 / 3) - (2 / 3)
        )
        self.assertIn("UNKNOWN", result["rate_delta_by_route"])
        percentiles = result["latency_percentiles"]
        self.assertEqual(percentiles["p50"]["old"], 100)
        self.assertEqual(percentiles["p50"]["new"], 100)
        self.assertEqual(percentiles["p95"]["new"], 300)
        self.assertEqual(percentiles["p95"]["delta"], 200)
        markdown = to_markdown(result, old_run_id="old", new_run_id="new")
        self.assertIn("按分区正确率变化", markdown)
        self.assertIn("P95", markdown)
        self.assertNotIn("None", markdown)

    def test_missing_run_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_run_records(self.root, "absent")


if __name__ == "__main__":
    unittest.main()
