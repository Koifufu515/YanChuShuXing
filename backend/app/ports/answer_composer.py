from __future__ import annotations

from typing import Any, Protocol

from app.application.answer_models import (
    AnalysisFacts,
    AnswerPayload,
)


class AnswerComposer(Protocol):
    def compose(
        self,
        question: str,
        query_plan: dict[str, Any],
        facts: AnalysisFacts,
    ) -> AnswerPayload:
        ...
