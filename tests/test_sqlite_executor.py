import tempfile
import unittest
from pathlib import Path

from app.application.errors import QueryExecutionError, QueryTimeoutError
from app.adapters.database.init_db import initialize_database


ROOT = Path(__file__).resolve().parents[1]


class SQLiteExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "bankinsight.db"
        initialize_database(self.database_path, ROOT / "sql" / "schema.sql")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_executes_parameterized_readonly_query_with_limit(self) -> None:
        from app.adapters.database.sqlite_executor import SQLiteExecutor

        executor = SQLiteExecutor(self.database_path)
        result = executor.execute_query(
            """
            SELECT customer_id, customer_level
            FROM customer_info
            WHERE customer_status = :status
            ORDER BY customer_id
            """,
            {"status": "ACTIVE"},
            max_rows=1,
        )

        self.assertEqual(result.columns, ["customer_id", "customer_level"])
        self.assertEqual(result.rows, [["C001", "HNW"]])
        self.assertEqual(result.row_count, 1)
        self.assertTrue(result.truncated)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_converts_database_errors_to_application_error(self) -> None:
        from app.adapters.database.sqlite_executor import SQLiteExecutor

        executor = SQLiteExecutor(self.database_path)
        with self.assertRaises(QueryExecutionError):
            executor.execute_query(
                "SELECT missing_column FROM customer_info", {}, max_rows=10
            )

    def test_readonly_connection_rejects_write_operations(self) -> None:
        from app.adapters.database.sqlite_executor import SQLiteExecutor

        executor = SQLiteExecutor(self.database_path)
        with self.assertRaises(QueryExecutionError):
            executor.execute_query("DELETE FROM customer_info", {}, max_rows=10)

    def test_long_running_query_is_interrupted(self) -> None:
        from app.adapters.database.sqlite_executor import SQLiteExecutor

        executor = SQLiteExecutor(
            self.database_path,
            query_timeout_seconds=0.0001,
            progress_steps=100,
        )
        with self.assertRaises(QueryTimeoutError):
            executor.execute_query(
                """
                WITH RECURSIVE numbers(value) AS (
                    VALUES(0)
                    UNION ALL
                    SELECT value + 1 FROM numbers WHERE value < 100000000
                )
                SELECT SUM(value) FROM numbers
                """,
                {},
                max_rows=10,
            )


if __name__ == "__main__":
    unittest.main()
