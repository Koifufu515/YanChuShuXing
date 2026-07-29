from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.application.models import AuditEvent
from app.application.security_alerts import (
    SecurityAlert,
    SecurityAlertMonitor,
)
from app.ports.audit_logger import AuditLogger


class AlertingAuditLogger:
    """
    先记录普通审计事件，再识别并追加安全告警。

    告警文件不保存原始用户标识、问题或SQL。
    """

    def __init__(
        self,
        delegate: AuditLogger,
        alert_path: Path,
        monitor: SecurityAlertMonitor | None = None,
    ) -> None:
        self.delegate = delegate
        self.alert_path = Path(alert_path)
        self.monitor = monitor or SecurityAlertMonitor()
        self._lock = Lock()

    def record(self, event: AuditEvent) -> None:
        self.delegate.record(event)

        with self._lock:
            alerts = self.monitor.evaluate(event)

            for alert in alerts:
                self._append_alert(
                    event,
                    alert,
                )

    def _append_alert(
        self,
        event: AuditEvent,
        alert: SecurityAlert,
    ) -> None:
        payload = {
            "event_version": 1,
            "occurred_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "event_count": alert.event_count,
            "window_seconds": alert.window_seconds,
            "security_action": alert.security_action,
            "trigger_event_type": event.event_type,
            "trigger_error_code": event.error_code,
            "request_id": event.request_id,
            "actor_sha256": hashlib.sha256(
                event.user_id.encode("utf-8")
            ).hexdigest(),
        }

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        self.alert_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        descriptor = os.open(
            self.alert_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )

        with os.fdopen(
            descriptor,
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        try:
            os.chmod(
                self.alert_path,
                0o600,
            )
        except OSError:
            pass
