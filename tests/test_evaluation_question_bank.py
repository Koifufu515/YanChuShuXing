import tempfile
import unittest
from pathlib import Path

from evaluation.models import EvalQuestion
from evaluation.question_bank import (
    load_questions,
    parse_question_id,
    write_questions,
)


def _question(question_id: str, partition: str, difficulty: str) -> EvalQuestion:
    return EvalQuestion(
        question_id=question_id,
        partition=partition,
        difficulty=difficulty,
        question_type="合成类型",
        question_text=f"合成题面{question_id}",
        official_answer=f"合成答案{question_id}",
    )


class ParseQuestionIdTest(unittest.TestCase):
    def test_parses_partition_and_difficulty(self) -> None:
        self.assertEqual(parse_question_id("TRAIN-S-01"), ("TRAIN", "S"))
        self.assertEqual(parse_question_id("VAL-M-40"), ("VAL", "M"))
        self.assertEqual(parse_question_id("TST-H-12"), ("TST", "H"))

    def test_rejects_malformed_ids(self) -> None:
        for bad in ("TRAIN-S", "DEV-S-01", "TRAIN-X-01", "TRAIN-S-AB", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_question_id(bad)


class LoadQuestionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "questions.jsonl"
        write_questions(
            [
                _question("TRAIN-S-01", "TRAIN", "S"),
                _question("TRAIN-M-02", "TRAIN", "M"),
                _question("VAL-S-01", "VAL", "S"),
                _question("TST-H-01", "TST", "H"),
            ],
            self.path,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_loads_all_and_round_trips(self) -> None:
        questions = load_questions(self.path)
        self.assertEqual(len(questions), 4)
        self.assertEqual(questions[0].question_text, "合成题面TRAIN-S-01")

    def test_filters_by_partition_ids_and_limit(self) -> None:
        train_only = load_questions(self.path, partitions={"TRAIN"})
        self.assertEqual([q.question_id for q in train_only], ["TRAIN-S-01", "TRAIN-M-02"])

        picked = load_questions(self.path, ids={"VAL-S-01"})
        self.assertEqual([q.question_id for q in picked], ["VAL-S-01"])

        limited = load_questions(self.path, partitions={"TRAIN"}, limit=1)
        self.assertEqual([q.question_id for q in limited], ["TRAIN-S-01"])

    def test_missing_file_raises_with_hint(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_questions(Path(self.tempdir.name) / "absent.jsonl")


if __name__ == "__main__":
    unittest.main()
