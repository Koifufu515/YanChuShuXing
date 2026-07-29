from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.adapters.audit.jsonl_alert_reader import (
    JsonlSecurityAlertReader,
)
from app.adapters.security.token_authenticator import (
    TokenAuthenticator,
)
from app.api.query import (
    get_query_audit_logger,
    get_token_authenticator,
)
from app.api.security_alerts import (
    get_security_alert_reader,
)
from app.application.security_alerts import (
    SecurityAlertRecord,
)
from app.application.security_models import (
    SecurityPrincipal,
)
from app.bootstrap import container
from app.main import app


TOKEN = "app_security_token_1234567890"


class FakeAlertReader:
    def read_recent(
        self,
        limit: int = 50,
    ):
        return [
            SecurityAlertRecord(
                occurred_at=datetime(
                    2026,
                    7,
                    29,
                    9,
                    0,
                    tzinfo=timezone.utc,
                ),
                alert_type=(
                    "repeated_institution_scope_denial"
                ),
                severity="high",
                event_count=3,
                window_seconds=600,
                security_action=(
                    "institution_denial_threshold"
                ),
                trigger_event_type=(
                    "access_denied"
                ),
                trigger_error_code=(
                    "ACCESS_DENIED"
                ),
                request_id="req_alert_app",
                actor_sha256="b" * 64,
            )
        ][:limit]


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


def principal(
    role: str,
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id=f"user_{role}",
        display_name=role,
        role=role,
        allowed_institution_ids=(
            frozenset({"*"})
        ),
        masking_profile="none",
        authenticated=True,
    )


class SecurityAlertAppIntegrationTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.previous_overrides = dict(
            app.dependency_overrides
        )
        self.audit_logger = (
            CapturingAuditLogger()
        )

        app.dependency_overrides[
            get_security_alert_reader
        ] = lambda: FakeAlertReader()

        app.dependency_overrides[
            get_query_audit_logger
        ] = lambda: self.audit_logger

        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(
            self.previous_overrides
        )

    def configure_role(
        self,
        role: str,
    ) -> None:
        authenticator = TokenAuthenticator(
            authentication_required=True,
            principals_by_token={
                TOKEN: principal(role)
            },
        )

        app.dependency_overrides[
            get_token_authenticator
        ] = lambda: authenticator

    def test_container_builds_private_reader(
        self,
    ) -> None:
        reader = (
            container
            .build_security_alert_reader()
        )

        self.assertIsInstance(
            reader,
            JsonlSecurityAlertReader,
        )
        self.assertEqual(
            reader.path,
            (
                container.PROJECT_ROOT
                / "data"
                / "private"
                / "audit"
                / "security_alerts.jsonl"
            ),
        )

    def test_admin_reads_alerts_from_main_app(
        self,
    ) -> None:
        self.configure_role("admin")

        response = self.client.get(
            "/api/v1/security/alerts?limit=10",
            headers={
                "Authorization": (
                    f"Bearer {TOKEN}"
                )
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        body = response.json()

        self.assertEqual(
            body["count"],
            1,
        )
        self.assertEqual(
            body["alerts"][0]["severity"],
            "high",
        )
        self.assertEqual(
            body["alerts"][0][
                "actor_fingerprint"
            ],
            "b" * 12,
        )
        self.assertNotIn(
            "b" * 64,
            response.text,
        )
        self.assertEqual(
            self.audit_logger.events[-1]
            .event_type,
            "security_alerts_read",
        )

    def test_analyst_is_denied_by_main_app(
        self,
    ) -> None:
        self.configure_role(
            "province_analyst"
        )

        response = self.client.get(
            "/api/v1/security/alerts",
            headers={
                "Authorization": (
                    f"Bearer {TOKEN}"
                )
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertEqual(
            response.json()["error"]["code"],
            "ALERT_ACCESS_DENIED",
        )


if __name__ == "__main__":
    unittest.main()
