import unittest
from pathlib import Path

from app.application.errors import UnsupportedQuestionError


ROOT = Path(__file__).resolve().parents[1]


class RuleSQLGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.adapters.context.yaml_resolver import YAMLContextResolver
        from app.adapters.generation.rule_generator import RuleSQLGenerator

        self.resolver = YAMLContextResolver(
            ROOT / "config" / "schema.yml",
            ROOT / "config" / "metrics.yml",
        )
        self.generator = RuleSQLGenerator()

    def test_generates_active_customer_count_query(self) -> None:
        question = "查询有效客户数量"
        context = self.resolver.resolve(question)
        generated = self.generator.generate(question, context)

        self.assertIn("customer_info", context.allowed_tables)
        self.assertIn("active_customer_count", context.metric_context)
        self.assertIn("COUNT", generated.sql.upper())
        self.assertEqual(generated.parameters, {"status": "ACTIVE"})

    def test_generates_parameterized_customer_balance_query(self) -> None:
        question = "查询客户C001的账户余额"
        context = self.resolver.resolve(question)
        generated = self.generator.generate(question, context)

        self.assertEqual(
            context.allowed_tables, frozenset({"customer_info", "account_info"})
        )
        self.assertNotIn("C001", generated.sql)
        self.assertEqual(generated.parameters["customer_id"], "C001")

    def test_generates_parameterized_monthly_transaction_summary(self) -> None:
        question = "查询客户C001在2026年6月的交易汇总"
        context = self.resolver.resolve(question)
        generated = self.generator.generate(question, context)

        self.assertNotIn("C001", generated.sql)
        self.assertEqual(generated.parameters["customer_id"], "C001")
        self.assertEqual(generated.parameters["start_time"], "2026-06-01 00:00:00")
        self.assertEqual(generated.parameters["end_time"], "2026-07-01 00:00:00")

    def test_rejects_unsupported_question(self) -> None:
        question = "预测明年的股票价格"
        context = self.resolver.resolve(question)
        with self.assertRaises(UnsupportedQuestionError):
            self.generator.generate(question, context)

    def test_rejects_unapproved_alias_outside_three_gold_questions(self) -> None:
        question = "查询客户数量"
        context = self.resolver.resolve(question)
        with self.assertRaises(UnsupportedQuestionError):
            self.generator.generate(question, context)


if __name__ == "__main__":
    unittest.main()
