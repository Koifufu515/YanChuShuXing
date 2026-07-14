from typing import Protocol

from app.application.models import FormattedResult, QueryResult


class ResultFormatter(Protocol):
    def format(self, question: str, result: QueryResult) -> FormattedResult: ...
