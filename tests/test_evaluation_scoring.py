import unittest

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_EXCLUDED_ANOMALY,
    SCORE_INCORRECT,
    SCORE_NEEDS_MANUAL_REVIEW,
    SCORE_NOT_SCORED_SYSTEM_ERROR,
    EvalQuestion,
)
from evaluation.scoring import RULES_VERSION, score


def _question(official_answer: str, question_id: str = "TRAIN-S-01") -> EvalQuestion:
    return EvalQuestion(
        question_id=question_id,
        partition="TRAIN",
        difficulty="S",
        question_type="合成",
        question_text="合成题面",
        official_answer=official_answer,
    )


class ScoreSystemStatesTest(unittest.TestCase):
    def test_system_error_is_not_scored(self) -> None:
        result = score(
            _question("答案为1.5亿元"),
            summary=None,
            rows=[],
            error_code="QUERY_TIMEOUT",
        )
        self.assertEqual(result.status, SCORE_NOT_SCORED_SYSTEM_ERROR)

    def test_anomaly_question_is_excluded(self) -> None:
        result = score(
            _question("答案为1.5亿元", question_id="TRAIN-M-46"),
            summary="任意",
            rows=[],
            anomaly_ids=frozenset({"TRAIN-M-46"}),
        )
        self.assertEqual(result.status, SCORE_EXCLUDED_ANOMALY)


class ScoreNumericTest(unittest.TestCase):
    def test_correct_when_all_official_numbers_match(self) -> None:
        result = score(
            _question("余额为1.5亿元"),
            summary="查询结果：余额合计15000.00万元",
            rows=[["合计", 150000000]],
        )
        self.assertEqual(result.status, SCORE_CORRECT)

    def test_incorrect_when_number_differs(self) -> None:
        result = score(
            _question("不良率为1.23%"),
            summary="不良率为1.32%",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_INCORRECT)

    def test_rows_participate_in_matching(self) -> None:
        result = score(
            _question("净利润为300元"),
            summary="查询返回1条记录。",
            rows=[["测试省甲市农商行", 300]],
        )
        self.assertEqual(result.status, SCORE_CORRECT)


class ScoreOrgListTest(unittest.TestCase):
    def test_correct_when_org_sequence_matches_in_order(self) -> None:
        result = score(
            _question("前两名依次为测试省甲市农商行、测试省乙市农商行"),
            summary="排名：1. 测试省甲市农商行 2. 测试省乙市农商行",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_CORRECT)

    def test_incorrect_when_order_swapped(self) -> None:
        result = score(
            _question("前两名依次为测试省甲市农商行、测试省乙市农商行"),
            summary="排名：1. 测试省乙市农商行 2. 测试省甲市农商行",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_INCORRECT)

    def test_incorrect_when_org_missing(self) -> None:
        result = score(
            _question("前两名依次为测试省甲市农商行、测试省乙市农商行"),
            summary="仅返回测试省甲市农商行",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_INCORRECT)


class ScoreHonestFallbackTest(unittest.TestCase):
    def test_unparseable_official_answer_needs_manual_review(self) -> None:
        result = score(
            _question("整体经营稳健，无明显异常"),
            summary="系统摘要",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_NEEDS_MANUAL_REVIEW)

    def test_rules_version(self) -> None:
        self.assertTrue(RULES_VERSION.startswith("score-"))


if __name__ == "__main__":
    unittest.main()
