from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "seed_permission_demo.py"

spec = importlib.util.spec_from_file_location(
    "seed_permission_demo",
    SCRIPT_PATH,
)
if spec is None or spec.loader is None:
    raise RuntimeError(
        "无法加载权限演示数据初始化脚本。"
    )

seed_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_module)

seed_permission_demo = (
    seed_module.seed_permission_demo
)
TABLE_NAME = seed_module.TABLE_NAME


class PermissionDemoSeedTest(unittest.TestCase):
    def create_database(
        self,
        path: Path,
        institution_ids: list[str],
    ) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                CREATE TABLE institutions (
                    institution_id TEXT PRIMARY KEY,
                    institution_name TEXT NOT NULL
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO institutions (
                    institution_id,
                    institution_name
                )
                VALUES (?, ?)
                """,
                [
                    (
                        institution_id,
                        f"演示机构{index}",
                    )
                    for index, institution_id
                    in enumerate(
                        institution_ids,
                        start=1,
                    )
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def test_seed_creates_expected_synthetic_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = (
                Path(directory) / "demo.db"
            )
            self.create_database(
                database,
                ["ORG009", "ORG010", "ORG011"],
            )

            first_org, second_org, count = (
                seed_permission_demo(database)
            )

            self.assertEqual(first_org, "ORG009")
            self.assertEqual(second_org, "ORG010")
            self.assertEqual(count, 6)

            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    f"""
                    SELECT
                        customer_id,
                        institution_id,
                        rm_id,
                        customer_name,
                        phone,
                        id_card,
                        account_number,
                        data_classification
                    FROM {TABLE_NAME}
                    ORDER BY customer_id
                    """
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(len(rows), 6)
            self.assertTrue(
                all(
                    row[0].startswith("DEMO-C")
                    for row in rows
                )
            )
            self.assertTrue(
                all(
                    row[3].startswith("演示客户")
                    for row in rows
                )
            )
            self.assertTrue(
                all(
                    row[5].startswith("DEMO-ID-")
                    for row in rows
                )
            )
            self.assertTrue(
                all(
                    row[6].startswith(
                        "DEMO-ACCOUNT-"
                    )
                    for row in rows
                )
            )
            self.assertTrue(
                all(
                    row[7]
                    == "synthetic_permission_demo"
                    for row in rows
                )
            )

            distribution = {
                (row[0], row[1]): row[2]
                for row in rows
            }
            self.assertEqual(
                distribution[("ORG009", "RM001")],
                2,
            )
            self.assertEqual(
                distribution[("ORG009", "RM002")],
                1,
            )
            self.assertEqual(
                distribution[("ORG010", "RM003")],
                2,
            )
            self.assertEqual(
                distribution[("ORG010", "RM004")],
                1,
            )

    def test_seed_uses_first_two_available_institutions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = (
                Path(directory) / "fallback.db"
            )
            self.create_database(
                database,
                ["ORG101", "ORG102", "ORG103"],
            )

            first_org, second_org, count = (
                seed_permission_demo(database)
            )

            self.assertEqual(first_org, "ORG101")
            self.assertEqual(second_org, "ORG102")
            self.assertEqual(count, 6)

    def test_seed_is_repeatable_without_duplicate_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = (
                Path(directory) / "repeatable.db"
            )
            self.create_database(
                database,
                ["ORG009", "ORG010"],
            )

            seed_permission_demo(database)
            seed_permission_demo(database)

            connection = sqlite3.connect(database)
            try:
                count = connection.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {TABLE_NAME}
                    """
                ).fetchone()[0]

                index_names = {
                    row[1]
                    for row in connection.execute(
                        f"""
                        PRAGMA index_list(
                            {TABLE_NAME}
                        )
                        """
                    )
                }
            finally:
                connection.close()

            self.assertEqual(count, 6)
            self.assertIn(
                "idx_demo_portfolio_institution",
                index_names,
            )
            self.assertIn(
                "idx_demo_portfolio_rm",
                index_names,
            )


if __name__ == "__main__":
    unittest.main()
