import json
import unittest

from app.application.errors import InvalidProviderOutputError, UnsupportedQuestionError
from app.application.models import LLMResponse, QueryContext


class FakeLLMProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        text = self.responses.pop(0)
        return LLMResponse(text=text, model="fake-model", latency_ms=12)


SEMANTIC = {
    "intent": "customer_account_balance",
    "business_domain": "customer_asset",
    "metrics": ["deposit_balance"],
    "dimensions": ["customer_id"],
    "filters": {"customer_id": "C001"},
    "time_range": None,
    "sort": [],
    "limit": None,
    "clarification_required": False,
    "clarification_question": None,
}


class LLMSQLGeneratorTest(unittest.TestCase):
    def setUp(self):
        self.context = QueryContext(
            schema_context="tables:\n  account_info:\n    columns:\n      customer_id: {}\n      current_balance: {}\n",
            metric_context="metrics:\n  - id: deposit_balance\n",
            allowed_tables=frozenset({"account_info"}),
        )

    def _generator(self, *responses):
        from app.adapters.generation.llm_generator import LLMSQLGenerator

        provider = FakeLLMProvider(responses)
        return LLMSQLGenerator(provider), provider

    def test_valid_two_stage_output_returns_parameterized_sql(self):
        generator, provider = self._generator(
            json.dumps(SEMANTIC),
            json.dumps(
                {
                    "sql": "SELECT SUM(current_balance) FROM account_info WHERE customer_id = :customer_id",
                    "parameters": {"customer_id": "C001"},
                    "warnings": [],
                }
            ),
        )

        generated = generator.generate("查询客户C001的账户余额", self.context)

        self.assertEqual(generated.parameters, {"customer_id": "C001"})
        self.assertEqual(generated.generator_name, "llm:fake-model")
        self.assertEqual(len(provider.requests), 2)
        self.assertIn("deposit_balance", provider.requests[0].user_prompt)
        self.assertIn("customer_account_balance", provider.requests[1].user_prompt)
        self.assertIn("account_balance", provider.requests[1].user_prompt)
        self.assertIn("monthly_transaction_summary", provider.requests[0].system_prompt)
        self.assertIn("business_domain=transaction", provider.requests[0].system_prompt)

    def test_invalid_semantic_json_and_markdown_are_rejected(self):
        for output in ("not json", "```json\n{}\n```"):
            with self.subTest(output=output):
                generator, _ = self._generator(output)
                with self.assertRaises(InvalidProviderOutputError):
                    generator.generate("问题", self.context)

    def test_unknown_metric_is_rejected_before_sql_stage(self):
        semantic = {**SEMANTIC, "metrics": ["invented_metric"]}
        generator, provider = self._generator(json.dumps(semantic))
        with self.assertRaises(InvalidProviderOutputError):
            generator.generate("问题", self.context)
        self.assertEqual(len(provider.requests), 1)

    def test_clarification_required_returns_structured_error(self):
        semantic = {
            **SEMANTIC,
            "clarification_required": True,
            "clarification_question": "请提供客户编号。",
        }
        generator, _ = self._generator(json.dumps(semantic))
        with self.assertRaisesRegex(UnsupportedQuestionError, "客户编号"):
            generator.generate("查余额", self.context)

    def test_invalid_sql_json_empty_and_markdown_are_rejected(self):
        for output in ("not json", "", "```json\n{}\n```"):
            with self.subTest(output=output):
                generator, _ = self._generator(json.dumps(SEMANTIC), output)
                with self.assertRaises(InvalidProviderOutputError):
                    generator.generate("问题", self.context)

    def test_sql_parameters_must_be_json_scalars(self):
        generator, _ = self._generator(
            json.dumps(SEMANTIC),
            json.dumps({"sql": "SELECT 1", "parameters": {"x": [1]}, "warnings": []}),
        )
        with self.assertRaises(InvalidProviderOutputError):
            generator.generate("问题", self.context)
