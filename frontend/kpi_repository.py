from __future__ import annotations

import sqlite3
from pathlib import Path


OVERVIEW_QUERIES = (
    ("有效客户数", "SELECT COUNT(*) FROM customer_info WHERE customer_status = 'ACTIVE'"),
    ("账户数量", "SELECT COUNT(*) FROM account_info"),
    ("交易总数", "SELECT COUNT(*) FROM transaction_detail"),
    ("理财产品数", "SELECT COUNT(*) FROM wealth_product"),
)


def load_overview_metrics(database_path: Path) -> list[tuple[str, int]]:
    path = Path(database_path).resolve()
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise OSError("经营概览数据暂时不可用。") from error
    try:
        return [
            (label, int(connection.execute(sql).fetchone()[0]))
            for label, sql in OVERVIEW_QUERIES
        ]
    except (sqlite3.Error, TypeError, ValueError) as error:
        raise OSError("经营概览数据暂时不可用。") from error
    finally:
        connection.close()
