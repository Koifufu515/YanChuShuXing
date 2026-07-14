import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DatabaseInitializationTest(unittest.TestCase):
    def test_initialization_is_repeatable_and_deterministic(self) -> None:
        from app.adapters.database.init_db import initialize_database

        with tempfile.TemporaryDirectory() as tmpdir:
            database_path = Path(tmpdir) / "bankinsight.db"
            schema_path = ROOT / "sql" / "schema.sql"

            initialize_database(database_path, schema_path)
            first = self._snapshot(database_path)
            initialize_database(database_path, schema_path)
            second = self._snapshot(database_path)

        self.assertEqual(first, second)
        self.assertEqual(first["table_count"], 10)
        self.assertEqual(first["customer_count"], 3)
        self.assertEqual(first["account_count"], 4)
        self.assertEqual(first["transaction_count"], 4)
        self.assertEqual(first["active_customer_count"], 2)
        self.assertEqual(first["c001_balance"], 6_000_000)

    @staticmethod
    def _snapshot(database_path: Path) -> dict[str, int]:
        with sqlite3.connect(database_path) as connection:
            table_count = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            customer_count = connection.execute(
                "SELECT COUNT(*) FROM customer_info"
            ).fetchone()[0]
            account_count = connection.execute(
                "SELECT COUNT(*) FROM account_info"
            ).fetchone()[0]
            transaction_count = connection.execute(
                "SELECT COUNT(*) FROM transaction_detail"
            ).fetchone()[0]
            active_customer_count = connection.execute(
                "SELECT COUNT(*) FROM customer_info WHERE customer_status = 'ACTIVE'"
            ).fetchone()[0]
            c001_balance = connection.execute(
                """
                SELECT SUM(current_balance)
                FROM account_info
                WHERE customer_id = 'C001' AND account_status = 'ACTIVE'
                """
            ).fetchone()[0]
        return {
            "table_count": table_count,
            "customer_count": customer_count,
            "account_count": account_count,
            "transaction_count": transaction_count,
            "active_customer_count": active_customer_count,
            "c001_balance": c001_balance,
        }


if __name__ == "__main__":
    unittest.main()
