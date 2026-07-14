import json
import unittest
from pathlib import Path

import yaml

from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.generation.hybrid_generator import HybridSQLGenerator
from app.adapters.generation.llm_generator import LLMSQLGenerator
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.application.errors import ProviderTimeoutError, RuleNotMatchedError
from app.application.models import LLMResponse


ROOT = Path(__file__).resolve().parents[1]
QUESTION = "查询客户C001在2026年6月的交易汇总"


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, request):
        return LLMResponse(
            text=self.responses.pop(0), model="fake-deepseek", latency_ms=10
        )


class FailingGenerator:
    def generate(self, question, context):
        raise ProviderTimeoutError("private timeout")


class MissingRule:
    def generate(self, question, context):
        raise RuleNotMatchedError("not matched")


class ExplainabilityTest(unittest.TestCase):
    def setUp(self):
        self.resolver = YAMLContextResolver(
            ROOT / "config" / "schema.yml", ROOT / "config" / "metrics.yml"
        )

    def test_rule_metadata_is_minimal(self):
        generated = RuleSQLGenerator().generate(
            "查询有效客户数量", self.resolver.resolve("查询有效客户数量")
        )
        self.assertEqual(generated.metadata.configured_mode, "rule")
        self.assertEqual(generated.metadata.executed_generator, "rule")
        self.assertTrue(generated.metadata.rule_matched)
        self.assertEqual(generated.metadata.route, "Rule")
        self.assertIsNone(generated.metadata.failure_reason)
        self.assertIsNone(generated.metadata.semantic)
        self.assertFalse(generated.metadata.fallback.used)

    def test_transaction_context_contains_four_metrics(self):
        context = self.resolver.resolve(QUESTION)
        ids = {item["id"] for item in yaml.safe_load(context.metric_context)["metrics"]}
        self.assertEqual(
            ids,
            {
                "transaction_count",
                "transaction_inflow",
                "transaction_outflow",
                "net_transaction_flow",
            },
        )
        self.assertIn("transaction_status", context.schema_context)
        self.assertIn("direction", context.schema_context)
        self.assertIn("transaction_time", context.schema_context)

    def test_llm_transaction_metadata_and_parameterized_sql(self):
        semantic = {
            "intent": "monthly_transaction_summary",
            "business_domain": "transaction",
            "metrics": [
                "transaction_count",
                "transaction_inflow",
                "transaction_outflow",
                "net_transaction_flow",
            ],
            "dimensions": ["customer_id"],
            "filters": {"customer_id": "C001"},
            "time_range": {
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            },
            "sort": [],
            "limit": None,
            "clarification_required": False,
            "clarification_question": None,
            "confidence": 0.96,
        }
        sql = {
            "sql": "SELECT customer_id, COUNT(CASE WHEN transaction_status = 'SUCCESS' THEN 1 END) AS transaction_count, SUM(CASE WHEN transaction_status = 'SUCCESS' AND direction = 'IN' THEN amount ELSE 0 END) AS total_in, SUM(CASE WHEN transaction_status = 'SUCCESS' AND direction = 'OUT' THEN amount ELSE 0 END) AS total_out, SUM(CASE WHEN transaction_status = 'SUCCESS' AND direction = 'IN' THEN amount WHEN transaction_status = 'SUCCESS' AND direction = 'OUT' THEN -amount ELSE 0 END) AS net_amount FROM transaction_detail WHERE customer_id = :customer_id AND transaction_time >= :start_time AND transaction_time < :end_time GROUP BY customer_id",
            "parameters": {
                "customer_id": "C001",
                "start_time": "2026-06-01 00:00:00",
                "end_time": "2026-07-01 00:00:00",
            },
            "warnings": [],
        }
        generated = LLMSQLGenerator(
            FakeProvider([json.dumps(semantic), json.dumps(sql)]),
            configured_mode="hybrid",
        ).generate(QUESTION, self.resolver.resolve(QUESTION))
        self.assertEqual(generated.metadata.configured_mode, "hybrid")
        self.assertEqual(generated.metadata.executed_generator, "llm")
        self.assertEqual(generated.metadata.semantic.business_domain, "transaction")
        self.assertEqual(generated.metadata.semantic.confidence, 0.96)
        self.assertEqual(generated.metadata.llm_latency_ms, 20)
        self.assertIn(":customer_id", generated.sql)
        self.assertEqual(generated.parameters["end_time"], "2026-07-01 00:00:00")

    def test_hybrid_llm_failure_records_route_without_rule_fallback(self):
        with self.assertRaises(ProviderTimeoutError) as raised:
            HybridSQLGenerator(
            FailingGenerator(),
            MissingRule(),
            provider_name="deepseek",
            model="configured-model",
            ).generate("新问题", self.resolver.resolve("查询有效客户数量"))
        metadata = raised.exception.metadata
        self.assertEqual(metadata.configured_mode, "hybrid")
        self.assertEqual(metadata.executed_generator, "llm")
        self.assertFalse(metadata.fallback.used)
        self.assertEqual(metadata.route, "LLM")
        self.assertFalse(metadata.rule_matched)
        self.assertEqual(metadata.failure_reason, "llm_timeout")


if __name__ == "__main__":
    unittest.main()
