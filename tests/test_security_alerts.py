from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.application.models import AuditEvent
from app.application.security_alerts import (
    SecurityAlertMonitor,
)


START = datetime(
    2026,
    7,
    29,
    9,
    0,
    tzinfo=timezone.utc,
)


def event(
    *,
    event_type: str,
    action: str,
    user_id: str = "user_org009",
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        request_id="req_test",
        user_id=user_id,
        question="查询测试问题",
        error_code="ACCESS_DENIED",
        security_action=action,
    )


class SecurityAlertMonitorTest(
    unittest.TestCase
):
    def test_repeated_authentication_failure(
        self,
    ) -> None:
        monitor = SecurityAlertMonitor()

        for index in range(4):
            alerts = monitor.evaluate(
                event(
                    event_type=(
                        "authentication_failed"
                    ),
                    action=(
                        "invalid_bearer_token"
                    ),
                ),
                occurred_at=(
                    START
                    + timedelta(seconds=index * 20)
                ),
            )
            self.assertEqual(alerts, [])

        alerts = monitor.evaluate(
            event(
                event_type=(
                    "authentication_failed"
                ),
                action="invalid_bearer_token",
            ),
            occurred_at=START + timedelta(
                seconds=80
            ),
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(
            alerts[0].alert_type,
            "repeated_authentication_failure",
        )
        self.assertEqual(
            alerts[0].event_count,
            5,
        )

    def test_institution_scope_denial(
        self,
    ) -> None:
        monitor = SecurityAlertMonitor()

        for index in range(2):
            self.assertEqual(
                monitor.evaluate(
                    event(
                        event_type="access_denied",
                        action=(
                            "institution_scope_denied"
                        ),
                    ),
                    occurred_at=(
                        START
                        + timedelta(minutes=index)
                    ),
                ),
                [],
            )

        alerts = monitor.evaluate(
            event(
                event_type="access_denied",
                action=(
                    "institution_scope_denied"
                ),
            ),
            occurred_at=START + timedelta(
                minutes=2
            ),
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(
            alerts[0].severity,
            "high",
        )

    def test_high_frequency_denial(
        self,
    ) -> None:
        monitor = SecurityAlertMonitor()

        collected = []

        for index in range(10):
            collected.extend(
                monitor.evaluate(
                    event(
                        event_type="access_denied",
                        action=(
                            "field_access_denied"
                        ),
                    ),
                    occurred_at=(
                        START
                        + timedelta(seconds=index * 5)
                    ),
                )
            )

        self.assertEqual(
            [
                alert.alert_type
                for alert in collected
            ],
            [
                "high_frequency_security_denial"
            ],
        )
        self.assertEqual(
            collected[0].severity,
            "critical",
        )

    def test_cooldown_prevents_alert_storm(
        self,
    ) -> None:
        monitor = SecurityAlertMonitor(
            cooldown_seconds=600
        )

        alerts = []

        for index in range(6):
            alerts.extend(
                monitor.evaluate(
                    event(
                        event_type=(
                            "authentication_failed"
                        ),
                        action=(
                            "authentication_required"
                        ),
                    ),
                    occurred_at=(
                        START
                        + timedelta(seconds=index)
                    ),
                )
            )

        auth_alerts = [
            alert
            for alert in alerts
            if alert.alert_type
            == "repeated_authentication_failure"
        ]

        self.assertEqual(
            len(auth_alerts),
            1,
        )

    def test_success_event_does_not_alert(
        self,
    ) -> None:
        monitor = SecurityAlertMonitor()

        alerts = monitor.evaluate(
            event(
                event_type=(
                    "authentication_succeeded"
                ),
                action="token_authenticated",
            ),
            occurred_at=START,
        )

        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
