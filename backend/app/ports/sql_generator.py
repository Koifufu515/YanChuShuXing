from typing import Protocol

from app.application.models import GeneratedSQL, QueryContext


class SQLGenerator(Protocol):
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL: ...
