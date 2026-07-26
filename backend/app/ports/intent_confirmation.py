from __future__ import annotations

from typing import Protocol

from app.application.models import IntentResolution


class IntentConfirmationResolver(Protocol):
    def resolve(
        self, question: str, confirmation: dict | None
    ) -> IntentResolution: ...
