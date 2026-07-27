from __future__ import annotations

from typing import Protocol

from app.application.models import QueryPlanResult


class QueryPlanner(Protocol):
    def plan(self, question: str) -> QueryPlanResult:
        ...
