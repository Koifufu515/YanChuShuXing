from app.application.models import AuditEvent


class NoOpAuditLogger:
    def record(self, event: AuditEvent) -> None:
        return None
