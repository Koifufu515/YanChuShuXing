import unittest

from app.application.errors import (
    ClarificationRequiredError,
    InvalidProviderOutputError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RuleNotMatchedError,
    UnsupportedQuestionError,
)
from app.application.models import GeneratedSQL, QueryContext, QueryMetadata


class StubGenerator:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def generate(self, question, context):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class HybridGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.context = QueryContext("", "", frozenset())

    def test_rule_match_skips_llm(self):
        from app.adapters.generation.hybrid_generator import HybridSQLGenerator

        llm = StubGenerator(GeneratedSQL("SELECT 1", generator_name="llm:model"))
        rule = StubGenerator(GeneratedSQL("SELECT 2", generator_name="rule-v1"))
        result = HybridSQLGenerator(llm, rule).generate("问题", self.context)
        self.assertEqual(result.sql, "SELECT 2")
        self.assertEqual(rule.calls, 1)
        self.assertEqual(llm.calls, 0)
        self.assertTrue(result.metadata.rule_matched)
        self.assertEqual(result.metadata.route, "Rule")

    def test_rule_miss_uses_llm(self):
        from app.adapters.generation.hybrid_generator import HybridSQLGenerator

        llm = StubGenerator(
            GeneratedSQL(
                "SELECT 1",
                generator_name="llm:model",
                metadata=QueryMetadata("hybrid", "llm"),
            )
        )
        rule = StubGenerator(error=RuleNotMatchedError("not matched"))
        result = HybridSQLGenerator(llm, rule).generate("新问题", self.context)
        self.assertEqual(result.sql, "SELECT 1")
        self.assertEqual(rule.calls, 1)
        self.assertEqual(llm.calls, 1)
        self.assertFalse(result.metadata.rule_matched)
        self.assertEqual(result.metadata.route, "LLM")

    def test_llm_failure_never_retries_rule(self):
        from app.adapters.generation.hybrid_generator import HybridSQLGenerator

        for error, expected_reason in (
            (ProviderTimeoutError("timeout"), "llm_timeout"),
            (ProviderUnavailableError("offline"), "llm_unavailable"),
            (InvalidProviderOutputError("bad"), "invalid_llm_output"),
            (ClarificationRequiredError("请补充时间范围。"), "missing_parameter"),
        ):
            with self.subTest(error=error):
                llm = StubGenerator(error=error)
                rule = StubGenerator(error=RuleNotMatchedError("not matched"))
                with self.assertRaises(type(error)) as raised:
                    HybridSQLGenerator(llm, rule).generate("新问题", self.context)
                self.assertEqual(rule.calls, 1)
                self.assertEqual(llm.calls, 1)
                self.assertEqual(raised.exception.metadata.route, "LLM")
                self.assertFalse(raised.exception.metadata.rule_matched)
                self.assertEqual(
                    raised.exception.metadata.failure_reason, expected_reason
                )


if __name__ == "__main__":
    unittest.main()
