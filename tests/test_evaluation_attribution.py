import unittest

from evaluation.attribution import attribute
from evaluation.models import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    SCORE_NEEDS_MANUAL_REVIEW,
)


class AttributionTest(unittest.TestCase):
    def test_semantic_errors(self) -> None:
        for code in (
            "UNSUPPORTED_QUESTION",
            "CLARIFICATION_REQUIRED",
            "INVALID_SEMANTIC_OUTPUT",
            "UNSUPPORTED_METRIC",
            "INVALID_QUESTION",
        ):
            with self.subTest(code=code):
                result = attribute(code, SCORE_CORRECT)
                assert result is not None
                self.assertEqual(result.stage, "语义理解")

    def test_stage_mapping_samples(self) -> None:
        cases = {
            "INVALID_SQL_OUTPUT": "SQL生成",
            "LLM_TIMEOUT": "模型可用性",
            "LLM_UNAVAILABLE": "模型可用性",
            "LLM_PROVIDER_ERROR": "模型可用性",
            "SQL_REJECTED": "安全层",
            "ACCESS_DENIED": "安全层",
            "QUERY_EXECUTION_ERROR": "数据库执行",
            "QUERY_TIMEOUT": "数据库执行",
            "DATABASE_UNAVAILABLE": "数据库执行",
            "REQUEST_VALIDATION_ERROR": "接口校验",
            "API_CONNECTION_ERROR": "评测环境",
            "INTERNAL_ERROR": "系统内部",
        }
        for code, stage in cases.items():
            with self.subTest(code=code):
                result = attribute(code, SCORE_CORRECT)
                assert result is not None
                self.assertEqual(result.stage, stage)

    def test_unknown_code_falls_back(self) -> None:
        result = attribute("SOMETHING_NEW", SCORE_CORRECT)
        assert result is not None
        self.assertEqual(result.stage, "未分类错误")

    def test_no_error_correct_returns_none(self) -> None:
        self.assertIsNone(attribute(None, SCORE_CORRECT))

    def test_no_error_incorrect_is_result_mismatch(self) -> None:
        result = attribute(None, SCORE_INCORRECT)
        assert result is not None
        self.assertEqual(result.stage, "结果不一致")
        self.assertIn("06号", result.owner)

    def test_no_error_manual_review(self) -> None:
        result = attribute(None, SCORE_NEEDS_MANUAL_REVIEW)
        assert result is not None
        self.assertEqual(result.stage, "待人工判分")


if __name__ == "__main__":
    unittest.main()
