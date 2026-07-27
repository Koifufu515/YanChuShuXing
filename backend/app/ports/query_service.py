from __future__ import annotations

from typing import Protocol

from app.application.models import QueryCommand, QueryOutcome


class QueryService(Protocol):
    def run(self, command: QueryCommand) -> QueryOutcome:
        ...
