from typing import Protocol

from app.application.security_alerts import (
    SecurityAlertRecord,
)


class SecurityAlertReader(Protocol):
    def read_recent(
        self,
        limit: int = 50,
    ) -> list[SecurityAlertRecord]: ...
