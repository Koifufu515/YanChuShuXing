from __future__ import annotations

import unittest
from datetime import (
    datetime,
    timezone,
)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.security.token_authenticator import (
    TokenAuthenticator,
)
from app.api.query import (
    get_query_audit_logger,
    get_token_authenticator,
)
from app.api.security_alerts import (
    get_security_alert_reader,
    router,
)
from app.application.security_alerts import (
    SecurityAlertRecord,
)
from app.application.security_models import (
    SecurityPrincipal,
)


TOKEN = "security_test_token_1234567890"


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


class FakeAlertReader:
    def __init__(self) -> None:
        self.calls = []

    def read_recent(
        self,
        limit: int = 50,
    ):
        self.calls.append(limit)

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
                    "repeated_authentication_failure"
                ),
                severity="medium",
                event_count=5,
                window_seconds=300,
                security_action=(
                    "authentication_failure_threshold"
                ),
                trigger_event_type=(
                    "authentication_failed"
                ),
                trigger_error_code=(
                    "INVALID_AUTHENTICATION"
                ),
                request_id="req_alert_source",
                actor_sha256="a" * 64,
            )
        ]


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


class SecurityAlertAPITest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router)

        self.reader = FakeAlertReader()
        self.audit_logger = (
            CapturingAuditLogger()
        )

        self.app.dependency_overrides[
            get_security_alert_reader
        ] = lambda: self.reader

        self.app.dependency_overrides[
            get_query_audit_logger
        ] = lambda: self.audit_logger

        self.client = TestClient(
            self.app
        )

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.client.close()

    def configure_role(
        self,
        role: str,
    ) -> None:
        authenticator = TokenAuthenticator(
            authentication_required=False,
            principals_by_token={
                TOKEN: principal(role)
            },
        )

        self.app.dependency_overrides[
            get_token_authenticator
        ] = lambda: authenticator

    def test_missing_token_returns_401(
        self,
    ) -> None:
        self.configure_role("admin")

        response = self.client.get(
            "/api/v1/security/alerts"
        )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            response.json()["error"]["code"],
            "AUTHENTICATION_REQUIRED",
        )
        self.assertEqual(
            response.headers.get(
                "www-authenticate"
            ),
            "Bearer",
        )
        self.assertEqual(
            self.reader.calls,
            [],
        )

    def test_invalid_token_returns_401(
        self,
    ) -> None:
        self.configure_role("admin")

        response = self.client.get(
            "/api/v1/security/alerts",
            headers={
                "Authorization": (
                    "Bearer invalid_token_123456"
                )
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            response.json()["error"]["code"],
            "INVALID_AUTHENTICATION",
        )
        self.assertEqual(
            self.reader.calls,
            [],
        )

    def test_analyst_role_returns_403(
        self,
    ) -> None:
        self.configure_role(
            "institution_analyst"
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
        self.assertEqual(
            self.reader.calls,
            [],
        )

    def test_admin_and_auditor_can_read(
        self,
    ) -> None:
        for role in (
            "admin",
            "auditor",
        ):
            with self.subTest(role=role):
                self.configure_role(role)
                self.reader.calls.clear()

                response = self.client.get(
                    (
                        "/api/v1/security/"
                        "alerts?limit=20"
                    ),
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
                    self.reader.calls,
                    [20],
                )
                self.assertEqual(
                    body["alerts"][0][
                        "actor_fingerprint"
                    ],
                    "a" * 12,
                )
                self.assertNotIn(
                    "actor_sha256",
                    body["alerts"][0],
                )
                self.assertNotIn(
                    "a" * 64,
                    response.text,
                )


if __name__ == "__main__":
    unittest.main()
