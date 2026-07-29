from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from app.adapters.audit.alerting_logger import (
    AlertingAuditLogger,
)
from app.application.models import AuditEvent


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events = []

    def record(
        self,
        event: AuditEvent,
    ) -> None:
        self.events.append(event)


def failed_auth_event() -> AuditEvent:
    return AuditEvent(
        event_type="authentication_failed",
        request_id="req_alert_test",
        user_id="sensitive_user_org009",
        question="查询包含敏感内容的问题",
        error_code="INVALID_AUTHENTICATION",
        security_action="invalid_bearer_token",
    )


class AlertingAuditLoggerTest(
    unittest.TestCase
):
    def test_threshold_writes_private_alert(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "security_alerts.jsonl"
            delegate = CapturingAuditLogger()
            logger = AlertingAuditLogger(
                delegate,
                path,
            )

            for _ in range(5):
                logger.record(
                    failed_auth_event()
                )

            self.assertEqual(
                len(delegate.events),
                5,
            )
            self.assertTrue(
                path.exists()
            )

            lines = path.read_text(
                encoding="utf-8"
            ).splitlines()

            self.assertEqual(
                len(lines),
                1,
            )

            payload = json.loads(lines[0])

            self.assertEqual(
                payload["alert_type"],
                "repeated_authentication_failure",
            )
            self.assertEqual(
                payload["severity"],
                "medium",
            )
            self.assertEqual(
                payload["event_count"],
                5,
            )

            serialized = lines[0]

            self.assertNotIn(
                "sensitive_user_org009",
                serialized,
            )
            self.assertNotIn(
                "查询包含敏感内容的问题",
                serialized,
            )
            self.assertEqual(
                stat.S_IMODE(
                    path.stat().st_mode
                ),
                0o600,
            )

    def test_no_alert_before_threshold(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "security_alerts.jsonl"
            delegate = CapturingAuditLogger()
            logger = AlertingAuditLogger(
                delegate,
                path,
            )

            for _ in range(4):
                logger.record(
                    failed_auth_event()
                )

            self.assertEqual(
                len(delegate.events),
                4,
            )
            self.assertFalse(
                path.exists()
            )


if __name__ == "__main__":
    unittest.main()
