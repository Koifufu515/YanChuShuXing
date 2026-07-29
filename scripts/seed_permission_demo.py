from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


DEFAULT_DATABASE = Path(
    "data/private/runtime/bankinsight_real.db"
)

TABLE_NAME = "demo_customer_portfolio"


def select_demo_institutions(
    connection: sqlite3.Connection,
) -> tuple[str, str]:
    preferred = [
        row[0]
        for row in connection.execute(
            """
            SELECT institution_id
            FROM institutions
            WHERE institution_id IN ('ORG009', 'ORG010')
            ORDER BY institution_id
            """
        )
    ]

    if len(preferred) == 2:
        return preferred[0], preferred[1]

    available = [
        row[0]
        for row in connection.execute(
            """
            SELECT institution_id
            FROM institutions
            ORDER BY institution_id
            LIMIT 2
            """
        )
    ]

    if len(available) < 2:
        raise RuntimeError(
            "权限演示至少需要两个机构。"
        )

    return available[0], available[1]


def seed_permission_demo(
    database_path: Path,
) -> tuple[str, str, int]:
    if not database_path.exists():
        raise FileNotFoundError(
            f"数据库不存在：{database_path}"
        )

    connection = sqlite3.connect(database_path)

    try:
        first_org, second_org = (
            select_demo_institutions(connection)
        )

        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                customer_id TEXT PRIMARY KEY,
                institution_id TEXT NOT NULL,
                rm_id TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                id_card TEXT NOT NULL,
                account_number TEXT NOT NULL,
                aum_scaled INTEGER NOT NULL,
                risk_level TEXT NOT NULL,
                internal_remark TEXT NOT NULL,
                data_classification TEXT NOT NULL
                    DEFAULT 'synthetic_permission_demo',
                FOREIGN KEY (institution_id)
                    REFERENCES institutions(institution_id)
            )
            """
        )

        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS
            idx_demo_portfolio_institution
            ON {TABLE_NAME}(institution_id)
            """
        )

        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS
            idx_demo_portfolio_rm
            ON {TABLE_NAME}(rm_id)
            """
        )

        rows = [
            (
                "DEMO-C001",
                first_org,
                "RM001",
                "演示客户甲",
                "13800000001",
                "DEMO-ID-00000001",
                "DEMO-ACCOUNT-000001",
                125000000,
                "低",
                "合成数据：重点维护客户",
            ),
            (
                "DEMO-C002",
                first_org,
                "RM001",
                "演示客户乙",
                "13800000002",
                "DEMO-ID-00000002",
                "DEMO-ACCOUNT-000002",
                86000000,
                "中",
                "合成数据：近期资产波动",
            ),
            (
                "DEMO-C003",
                first_org,
                "RM002",
                "演示客户丙",
                "13800000003",
                "DEMO-ID-00000003",
                "DEMO-ACCOUNT-000003",
                42000000,
                "高",
                "合成数据：需要风险复核",
            ),
            (
                "DEMO-C004",
                second_org,
                "RM003",
                "演示客户丁",
                "13800000004",
                "DEMO-ID-00000004",
                "DEMO-ACCOUNT-000004",
                173000000,
                "低",
                "合成数据：资产配置稳定",
            ),
            (
                "DEMO-C005",
                second_org,
                "RM003",
                "演示客户戊",
                "13800000005",
                "DEMO-ID-00000005",
                "DEMO-ACCOUNT-000005",
                69000000,
                "中",
                "合成数据：近期联系客户",
            ),
            (
                "DEMO-C006",
                second_org,
                "RM004",
                "演示客户己",
                "13800000006",
                "DEMO-ID-00000006",
                "DEMO-ACCOUNT-000006",
                31000000,
                "高",
                "合成数据：持续风险观察",
            ),
        ]

        connection.execute(
            f"DELETE FROM {TABLE_NAME}"
        )

        connection.executemany(
            f"""
            INSERT INTO {TABLE_NAME} (
                customer_id,
                institution_id,
                rm_id,
                customer_name,
                phone,
                id_card,
                account_number,
                aum_scaled,
                risk_level,
                internal_remark,
                data_classification
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*row, "synthetic_permission_demo")
                for row in rows
            ],
        )

        connection.commit()

        count = connection.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME}"
        ).fetchone()[0]

        return first_org, second_org, count
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
    )
    arguments = parser.parse_args()

    first_org, second_org, count = (
        seed_permission_demo(
            arguments.database.resolve()
        )
    )

    print("权限演示表初始化完成。")
    print(f"表名：{TABLE_NAME}")
    print(f"演示机构：{first_org}、{second_org}")
    print(f"合成记录：{count} 条")


if __name__ == "__main__":
    main()
