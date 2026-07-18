from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from app.application.errors import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
)
from app.application.models import JsonScalar, QueryResult


class SQLiteExecutor:
    def __init__(
        self,
        database_path: Path,
        query_timeout_seconds: float = 2.0,
        progress_steps: int = 1000,
    ) -> None:
        if query_timeout_seconds <= 0:
            raise ValueError("query_timeout_seconds 必须大于0")
        if progress_steps <= 0:
            raise ValueError("progress_steps 必须大于0")
        self.database_path = Path(database_path).resolve()
        self.query_timeout_seconds = query_timeout_seconds
        self.progress_steps = progress_steps

    def execute_query(
        self,
        sql: str,
        parameters: dict[str, JsonScalar],
        max_rows: int = 1000,
    ) -> QueryResult:
        if not 1 <= max_rows <= 1000:
            raise ValueError("max_rows 必须位于 1 到 1000 之间")
        if not self.database_path.is_file():
            raise DatabaseUnavailableError("数据库尚未初始化。")

        started = perf_counter()
        deadline = started + self.query_timeout_seconds
        uri = f"{self.database_path.as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            try:
                connection.execute("PRAGMA query_only = ON")
                connection.set_progress_handler(
                    lambda: int(perf_counter() >= deadline), self.progress_steps
                )
                cursor = connection.execute(sql, parameters)
                if cursor.description is None:
                    raise QueryExecutionError("查询没有返回结果集。")
                columns = [column[0] for column in cursor.description]
                fetched = cursor.fetchmany(max_rows + 1)
            finally:
                connection.close()
        except QueryExecutionError:
            raise
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise QueryTimeoutError("数据库查询超时。") from exc
            raise QueryExecutionError("数据库查询执行失败。") from exc
        except sqlite3.Error as exc:
            raise QueryExecutionError("数据库查询执行失败。") from exc

        truncated = len(fetched) > max_rows
        rows = [
            [_to_json_scalar(value) for value in row]
            for row in fetched[:max_rows]
        ]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=(perf_counter() - started) * 1000,
        )


def _to_json_scalar(value: object) -> JsonScalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)
