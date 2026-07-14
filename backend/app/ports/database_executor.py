from typing import Protocol

from app.application.models import JsonScalar, QueryResult


class DatabaseExecutor(Protocol):
    def execute_query(
        self,
        sql: str,
        parameters: dict[str, JsonScalar],
        max_rows: int = 1000,
    ) -> QueryResult: ...
