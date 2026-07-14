from __future__ import annotations

import os
import sqlite3
from pathlib import Path


BRANCHES = [
    ("B000", "总行", "HEAD", None, "全国", "北京市", "北京市", "2000-01-01", "ACTIVE"),
    ("B101", "厦门分行", "TIER1", "B000", "华东", "福建省", "厦门市", "2010-05-01", "ACTIVE"),
    ("B102", "上海分行", "TIER1", "B000", "华东", "上海市", "上海市", "2008-03-01", "ACTIVE"),
]

MANAGERS = [
    ("M001", "陈经理", "B101", "2018-07-01", "SENIOR", "ACTIVE"),
]

CUSTOMERS = [
    ("C001", "M", 1985, "福建省", "T2", "BUSINESS_OWNER", "HNW", "C3", "2024-01-10", "B101", "M001", "ACTIVE"),
    ("C002", "F", 1992, "上海市", "T1", "EMPLOYEE", "AFFLUENT", "C2", "2025-02-15", "B102", None, "ACTIVE"),
    ("C003", "U", 1970, "福建省", "T2", "RETIRED", "MASS", "C1", "2023-06-01", "B101", "M001", "DORMANT"),
]

ACCOUNTS = [
    ("A001", "C001", "B101", "CURRENT", "CNY", "2024-01-10", None, 5_200_000, "ACTIVE"),
    ("A002", "C001", "B101", "TIME", "CNY", "2024-03-01", None, 800_000, "ACTIVE"),
    ("A003", "C002", "B102", "CURRENT", "CNY", "2025-02-15", None, 120_000, "ACTIVE"),
    ("A004", "C003", "B101", "CURRENT", "CNY", "2023-06-01", None, 10_000, "FROZEN"),
]

TRANSACTIONS = [
    ("T001", "A001", "C001", "B101", "2026-06-05 09:30:00", "DEPOSIT", "IN", 100_000, "APP", "SUCCESS", 0),
    ("T002", "A001", "C001", "B101", "2026-06-12 14:10:00", "PAYMENT", "OUT", 20_000, "APP", "SUCCESS", 0),
    ("T003", "A001", "C001", "B101", "2026-06-20 11:45:00", "TRANSFER_OUT", "OUT", 30_000, "WEB", "SUCCESS", 0),
    ("T004", "A001", "C001", "B101", "2026-06-22 16:20:00", "PAYMENT", "OUT", 5_000, "APP", "FAILED", 0),
]


def initialize_database(database_path: Path, schema_path: Path) -> Path:
    database_path = Path(database_path).resolve()
    schema_path = Path(schema_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = database_path.with_name(f".{database_path.name}.tmp")
    temporary_path.unlink(missing_ok=True)

    try:
        with sqlite3.connect(temporary_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            _insert_demo_data(connection)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"演示数据外键检查失败：{violations}")
            connection.commit()
        os.replace(temporary_path, database_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return database_path


def _insert_demo_data(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "INSERT INTO branch_info VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", BRANCHES
    )
    connection.executemany(
        "INSERT INTO customer_manager VALUES (?, ?, ?, ?, ?, ?)", MANAGERS
    )
    connection.executemany(
        "INSERT INTO customer_info VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        CUSTOMERS,
    )
    connection.executemany(
        "INSERT INTO account_info VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ACCOUNTS
    )
    connection.executemany(
        "INSERT INTO transaction_detail VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        TRANSACTIONS,
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[4]
    target = project_root / "data" / "processed" / "bankinsight.db"
    schema = project_root / "sql" / "schema.sql"
    initialized = initialize_database(target, schema)
    print(f"Initialized database: {initialized}")


if __name__ == "__main__":
    main()
