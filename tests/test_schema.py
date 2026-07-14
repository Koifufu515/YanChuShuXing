import sqlite3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("PRAGMA foreign_keys = ON")
        schema_sql = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
        self.connection.executescript(schema_sql)

    def tearDown(self) -> None:
        self.connection.close()

    def test_all_expected_tables_exist(self) -> None:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        names = {row[0] for row in rows}
        self.assertEqual(
            names,
            {
                "branch_info",
                "customer_manager",
                "customer_info",
                "account_info",
                "transaction_detail",
                "loan_info",
                "wealth_product",
                "product_purchase",
                "channel_behavior",
                "risk_event",
            },
        )

    def test_foreign_keys_are_enabled(self) -> None:
        enabled = self.connection.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(enabled, 1)

    def test_negative_account_balance_is_rejected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO branch_info (
                branch_id, branch_name, branch_level, region_name,
                province_name, city_name, open_date, status
            ) VALUES ('B1', '测试分行', 'TIER1', '华东', '福建省', '厦门市', '2020-01-01', 'ACTIVE')
            """
        )
        self.connection.execute(
            """
            INSERT INTO customer_info (
                customer_id, province_name, city_tier, occupation_type,
                customer_level, risk_preference, register_date, branch_id,
                customer_status
            ) VALUES ('C1', '福建省', 'T2', 'EMPLOYEE', 'MASS', 'C1', '2026-01-01', 'B1', 'ACTIVE')
            """
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "current_balance"):
            self.connection.execute(
                """
                INSERT INTO account_info (
                    account_id, customer_id, branch_id, account_type,
                    open_date, current_balance, account_status
                ) VALUES ('A1', 'C1', 'B1', 'CURRENT', '2026-01-01', -1, 'ACTIVE')
                """
            )


if __name__ == "__main__":
    unittest.main()
