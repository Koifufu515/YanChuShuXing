from __future__ import annotations

from typing import Any, Protocol

from app.application.models import QueryPlanExecutionResult


class QueryPlanExecutor(Protocol):
    def execute(self, query_plan: dict[str, Any]) -> QueryPlanExecutionResult:
        ...
