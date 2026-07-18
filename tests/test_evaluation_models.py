import unittest

from evaluation.models import (
    SCORE_NEEDS_MANUAL_REVIEW,
    EvalQuestion,
    EvalRecord,
)


class EvalModelTest(unittest.TestCase):
    def test_record_json_line_round_trip_preserves_chinese_and_none(self) -> None:
        record = EvalRecord(
            question_id="TRAIN-S-01",
            partition="TRAIN",
            difficulty="S",
            question_type="单值查询",
            run_id="run-demo-1",
            started_at="2026-07-18T10:00:00",
            sql=None,
            error_code="UNSUPPORTED_QUESTION",
            error_message="暂不支持该问题。",
            summary=None,
            rows=[["测试省甲市农商行", 1.23]],
            total_row_count=1,
        )
        line = record.to_json_line()
        self.assertNotIn("\n", line)
        self.assertIn("测试省甲市农商行", line)
        restored = EvalRecord.from_json_line(line)
        self.assertEqual(restored, record)

    def test_record_defaults(self) -> None:
        record = EvalRecord(
            question_id="VAL-M-02",
            partition="VAL",
            difficulty="M",
            question_type="排名",
            run_id="r",
            started_at="t",
        )
        self.assertEqual(record.score_status, SCORE_NEEDS_MANUAL_REVIEW)
        self.assertEqual(record.rows, [])
        self.assertIsNone(record.sql)

    def test_question_is_frozen(self) -> None:
        question = EvalQuestion(
            question_id="TST-H-01",
            partition="TST",
            difficulty="H",
            question_type="综合",
            question_text="合成题面",
            official_answer="合成答案",
        )
        with self.assertRaises(Exception):
            question.question_id = "X"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
