from typing import Protocol

from app.application.models import QueryContext


class ContextResolver(Protocol):
    def resolve(self, question: str) -> QueryContext: ...
