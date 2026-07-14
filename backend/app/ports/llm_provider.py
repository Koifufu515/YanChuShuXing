from typing import Protocol

from app.application.models import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...
