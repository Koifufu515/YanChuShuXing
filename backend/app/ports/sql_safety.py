from typing import Protocol

from app.application.models import SafetyResult, UserContext


class SQLSafetyChecker(Protocol):
    def validate(self, sql: str, user_context: UserContext) -> SafetyResult: ...
