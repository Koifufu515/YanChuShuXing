from typing import Protocol

from app.application.models import AuditEvent


class AuditLogger(Protocol):
    def record(self, event: AuditEvent) -> None: ...
