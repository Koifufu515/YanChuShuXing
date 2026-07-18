import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from evaluation.question_bank import load_questions
from scripts.extract_question_bank import EXPECTED_HEADER, extract


def _make_workbook(path: Path, rows: list[list[str]], header: list[str] | None = None) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "问题答案清单"
    sheet.append(header or EXPECTED_HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


class ExtractQuestionBankTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "synthetic.xlsx"
        self.output = self.root / "data" / "private" / "evaluation" / "questions.jsonl"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_extracts_rows_to_jsonl(self) -> None:
        _make_workbook(
            self.source,
            [
                ["TRAIN-S-01", "单值", "简单", "合成题面一", "合成答案一"],
                ["VAL-M-01", "排名", "中等", "合成题面二", "合成答案二"],
                ["TST-H-01", "综合", "困难", "合成题面三", "合成答案三"],
            ],
        )
        count = extract(self.source, self.output, enforce_counts=False)
        self.assertEqual(count, 3)
        questions = load_questions(self.output)
        self.assertEqual(questions[0].question_id, "TRAIN-S-01")
        self.assertEqual(questions[0].partition, "TRAIN")
        self.assertEqual(questions[0].difficulty, "S")
        self.assertEqual(questions[1].question_type, "排名")
        self.assertEqual(questions[2].official_answer, "合成答案三")

    def test_rejects_unexpected_header(self) -> None:
        _make_workbook(
            self.source,
            [["TRAIN-S-01", "单值", "简单", "题", "答"]],
            header=["编号", "类型", "难度", "描述", "结果"],
        )
        with self.assertRaises(ValueError):
            extract(self.source, self.output, enforce_counts=False)

    def test_rejects_output_outside_private_dir(self) -> None:
        _make_workbook(self.source, [["TRAIN-S-01", "单值", "简单", "题", "答"]])
        unsafe_output = self.root / "public" / "questions.jsonl"
        with self.assertRaises(ValueError):
            extract(self.source, unsafe_output, enforce_counts=False)

    def test_enforce_counts_rejects_wrong_partition_sizes(self) -> None:
        _make_workbook(
            self.source,
            [["TRAIN-S-01", "单值", "简单", "题", "答"]],
        )
        with self.assertRaises(ValueError):
            extract(self.source, self.output, enforce_counts=True)


if __name__ == "__main__":
    unittest.main()
