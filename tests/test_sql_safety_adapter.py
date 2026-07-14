import unittest

from app.application.models import UserContext


class SQLGlotSafetyAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker

        self.checker = SQLGlotSafetyChecker()
        self.context = UserContext(
            user_id="test_user",
            allowed_tables=frozenset({"customer_info", "customer_manager"}),
            denied_columns=frozenset({"manager_name"}),
        )

    def test_allows_single_select_and_cte(self) -> None:
        select_result = self.checker.validate(
            "SELECT customer_id FROM customer_info", self.context
        )
        cte_result = self.checker.validate(
            "WITH x AS (SELECT customer_id FROM customer_info) SELECT * FROM x",
            self.context,
        )
        self.assertTrue(select_result.allowed)
        self.assertTrue(cte_result.allowed)

    def test_rejects_write_and_multiple_statements(self) -> None:
        delete_result = self.checker.validate(
            "DELETE FROM customer_info", self.context
        )
        multi_result = self.checker.validate(
            "SELECT 1; DROP TABLE customer_info", self.context
        )
        self.assertFalse(delete_result.allowed)
        self.assertFalse(multi_result.allowed)
        self.assertEqual(delete_result.error_code, "SQL_REJECTED")
        self.assertEqual(multi_result.error_code, "SQL_REJECTED")

    def test_rejects_unknown_table_and_denied_column(self) -> None:
        table_result = self.checker.validate(
            "SELECT * FROM secret_table", self.context
        )
        column_result = self.checker.validate(
            "SELECT manager_name FROM customer_manager", self.context
        )
        self.assertFalse(table_result.allowed)
        self.assertFalse(column_result.allowed)
        self.assertIn("secret_table", table_result.referenced_tables)


if __name__ == "__main__":
    unittest.main()
