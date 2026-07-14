import unittest

from app.application.models import AuditEvent, QueryResult


class TemplateResultFormatterTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.adapters.formatting.template_formatter import TemplateResultFormatter

        self.formatter = TemplateResultFormatter()

    def test_formats_supported_query_summaries(self) -> None:
        cases = [
            (
                "查询有效客户数量",
                QueryResult(["customer_count"], [[2]], 1, False, 1.0),
                "当前有效客户数量为2户。",
            ),
            (
                "查询客户C001的账户余额",
                QueryResult(
                    ["customer_id", "account_balance"],
                    [["C001", 6_000_000]],
                    1,
                    False,
                    1.0,
                ),
                "客户C001当前有效账户余额合计为600.00万元。",
            ),
            (
                "查询客户C001在2026年6月的交易汇总",
                QueryResult(
                    [
                        "customer_id",
                        "transaction_count",
                        "total_in",
                        "total_out",
                        "net_amount",
                    ],
                    [["C001", 3, 100_000, 50_000, 50_000]],
                    1,
                    False,
                    1.0,
                ),
                "客户C001在该期间共有3笔成功交易，流入10.00万元，流出5.00万元，净流入5.00万元。",
            ),
        ]
        for question, result, expected in cases:
            with self.subTest(question=question):
                formatted = self.formatter.format(question, result)
                self.assertEqual(formatted.summary, expected)

    def test_formats_empty_and_truncated_results(self) -> None:
        empty = self.formatter.format(
            "查询客户C999的账户余额",
            QueryResult(["customer_id", "account_balance"], [], 0, False, 1.0),
        )
        truncated = self.formatter.format(
            "查询有效客户数量",
            QueryResult(["customer_count"], [[2]], 1, True, 1.0),
        )
        self.assertEqual(empty.summary, "未查询到符合条件的数据。")
        self.assertIn("已截断", truncated.warnings[0])

    def test_noop_audit_logger_accepts_events(self) -> None:
        from app.adapters.audit.noop_logger import NoOpAuditLogger

        NoOpAuditLogger().record(
            AuditEvent("request_started", "req1", "user1", "查询有效客户数量")
        )


if __name__ == "__main__":
    unittest.main()
