from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.version_compare import compare_runs, format_markdown_report, _recommend


def _write_scored(dir_path: Path, records: list[dict]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    with (dir_path / "scored_results.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class VersionCompareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_dir = self.root / "old_run"
        self.new_dir = self.root / "new_run"

    def tearDown(self):
        self.temp.cleanup()

    def _base_record(self, qid: str, comparison_status: str = "pass", **extra):
        return {
            "question_id": qid,
            "sequence": 1,
            "difficulty": "简单",
            "question_type": "单值",
            "comparison_status": comparison_status,
            "comparison_score": 1.0 if comparison_status == "pass" else 0.0,
            "run_status": "success",
            "duration_ms": 5000.0,
            "comparison": {"mode": "intent_aware_deterministic", "reason": ""},
            **extra,
        }

    def test_all_pass_no_change(self):
        _write_scored(self.old_dir, [self._base_record("Q-1", "pass")])
        _write_scored(self.new_dir, [self._base_record("Q-1", "pass")])
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertEqual(result["old_pass"], 1)
        self.assertEqual(result["new_pass"], 1)
        self.assertEqual(result["improved_count"], 0)
        self.assertEqual(result["regressed_count"], 0)
        self.assertEqual(result["recommendation"]["action"], "allow_merge")

    def test_improvement_detected(self):
        _write_scored(self.old_dir, [self._base_record("Q-1", "fail")])
        _write_scored(self.new_dir, [self._base_record("Q-1", "pass")])
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertEqual(result["improved_count"], 1)
        self.assertEqual(len(result["improved"]), 1)
        self.assertEqual(result["improved"][0]["question_id"], "Q-1")

    def test_regression_blocked(self):
        _write_scored(self.old_dir, [self._base_record("Q-1", "pass")])
        _write_scored(self.new_dir, [self._base_record("Q-1", "fail")])
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertEqual(result["regressed_count"], 1)
        self.assertEqual(result["recommendation"]["action"], "block_merge")

    def test_persistent_failure_tracked(self):
        _write_scored(self.old_dir, [self._base_record("Q-1", "fail")])
        _write_scored(self.new_dir, [self._base_record("Q-1", "fail")])
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertEqual(result["persistent_failure_count"], 1)

    def test_new_system_error_detected(self):
        _write_scored(
            self.old_dir,
            [self._base_record("Q-1", "pass", run_status="success")],
        )
        _write_scored(
            self.new_dir,
            [self._base_record("Q-1", "fail", run_status="failed",
                               comparison={"mode": "executable_answer", "reason": "LLM error"})],
        )
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertGreaterEqual(len(result["new_errors"]), 1)

    def test_multiple_questions_mixed(self):
        _write_scored(self.old_dir, [
            self._base_record("Q-1", "pass"),
            self._base_record("Q-2", "fail"),
            self._base_record("Q-3", "pass"),
        ])
        _write_scored(self.new_dir, [
            self._base_record("Q-1", "pass"),
            self._base_record("Q-2", "pass"),
            self._base_record("Q-3", "fail"),
        ])
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertEqual(result["improved_count"], 1)   # Q-2: fail→pass
        self.assertEqual(result["regressed_count"], 1)   # Q-3: pass→fail
        self.assertEqual(result["unchanged_count"], 1)   # Q-1: pass→pass
        self.assertEqual(result["recommendation"]["action"], "block_merge")

    def test_timing_stats(self):
        _write_scored(self.old_dir, [self._base_record("Q-1", "pass", duration_ms=1000.0)])
        _write_scored(self.new_dir, [self._base_record("Q-1", "pass", duration_ms=2000.0)])
        result = compare_runs(self.old_dir, self.new_dir)
        self.assertEqual(result["timing"]["old"]["mean"], 1000.0)
        self.assertEqual(result["timing"]["new"]["mean"], 2000.0)

    def test_markdown_report_generated(self):
        _write_scored(self.old_dir, [
            self._base_record("Q-1", "pass"),
            self._base_record("Q-2", "fail"),
        ])
        _write_scored(self.new_dir, [
            self._base_record("Q-1", "fail"),
            self._base_record("Q-2", "pass"),
        ])
        result = compare_runs(self.old_dir, self.new_dir)
        md = format_markdown_report(result)
        self.assertIn("版本评测对比报告", md)
        self.assertIn("退化项", md)
        self.assertIn("改善项", md)
        self.assertIn("阻塞合并", md)

    def test_empty_runs_raises(self):
        _write_scored(self.old_dir, [])
        _write_scored(self.new_dir, [])
        with self.assertRaises(ValueError):
            compare_runs(self.old_dir, self.new_dir)


if __name__ == "__main__":
    unittest.main()
