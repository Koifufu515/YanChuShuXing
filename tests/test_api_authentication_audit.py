from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.adapters.security.token_authenticator import (
    TokenAuthenticator,
)
from app.api.query import (
    get_query_audit_logger,
    get_query_pipeline,
    get_token_authenticator,
)
from app.application.models import (
    AuditEvent,
    QueryOutcome,
)
from app.application.security_models import (
    SecurityPrincipal,
)
from app.main import app


TOKEN = "audit_token_1234567890abcdef"


class CapturingPipeline:
    def __init__(self) -> None:
        self.commands = []

    def run(self, command):
        self.commands.append(command)

        return QueryOutcome(
            request_id=command.request_id,
            question=command.question,
            columns=["value"],
            rows=[[1]],
            summary="查询成功。",
        )


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(
        self,
        event: AuditEvent,
    ) -> None:
        self.events.append(event)


class FailingAuditLogger:
    def record(
        self,
        event: AuditEvent,
    ) -> None:
        raise OSError("模拟审计存储故障")


def principal() -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id="user_org009",
        display_name="I市机构分析岗",
        role="institution_analyst",
        allowed_institution_ids=(
            frozenset({"ORG009"})
        ),
        masking_profile="standard",
        authenticated=True,
    )


class APIAuthenticationAuditTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.pipeline = CapturingPipeline()
        self.logger = CapturingAuditLogger()

        self.authenticator = TokenAuthenticator(
            authentication_required=True,
            principals_by_token={
                TOKEN: principal(),
            },
        )

        app.dependency_overrides[
            get_query_pipeline
        ] = lambda: self.pipeline

        app.dependency_overrides[
            get_token_authenticator
        ] = lambda: self.authenticator

        app.dependency_overrides[
            get_query_audit_logger
        ] = lambda: self.logger

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()

    def test_missing_token_is_audited(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/query",
            json={
                "question": "查询不良贷款率",
                "user_id": "claimed_user",
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            self.pipeline.commands,
            [],
        )
        self.assertEqual(
            len(self.logger.events),
            1,
        )

        event = self.logger.events[0]

        self.assertEqual(
            event.event_type,
            "authentication_failed",
        )
        self.assertEqual(
            event.error_code,
            "AUTHENTICATION_REQUIRED",
        )
        self.assertEqual(
            event.security_action,
            "authentication_required",
        )
        self.assertFalse(
            event.authenticated
        )

    def test_invalid_token_is_audited(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/query",
            headers={
                "Authorization": (
                    "Bearer invalid_token_123456789"
                )
            },
            json={
                "question": "查询不良贷款率",
                "user_id": "claimed_user",
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )

        event = self.logger.events[0]

        self.assertEqual(
            event.error_code,
            "INVALID_AUTHENTICATION",
        )
        self.assertEqual(
            event.security_action,
            "invalid_bearer_token",
        )
        self.assertFalse(
            event.authenticated
        )

    def test_valid_token_is_audited(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/query",
            headers={
                "Authorization": (
                    f"Bearer {TOKEN}"
                )
            },
            json={
                "question": "查询不良贷款率",
                "user_id": "forged_user",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            len(self.pipeline.commands),
            1,
        )
        self.assertEqual(
            len(self.logger.events),
            1,
        )

        event = self.logger.events[0]

        self.assertEqual(
            event.event_type,
            "authentication_succeeded",
        )
        self.assertEqual(
            event.user_id,
            "user_org009",
        )
        self.assertEqual(
            event.actor_role,
            "institution_analyst",
        )
        self.assertTrue(
            event.authenticated
        )
        self.assertEqual(
            event.security_action,
            "token_authenticated",
        )

    def test_audit_storage_failure_does_not_break_query(
        self,
    ) -> None:
        app.dependency_overrides[
            get_query_audit_logger
        ] = lambda: FailingAuditLogger()

        response = self.client.post(
            "/api/v1/query",
            headers={
                "Authorization": (
                    f"Bearer {TOKEN}"
                )
            },
            json={
                "question": "查询不良贷款率",
                "user_id": "forged_user",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            len(self.pipeline.commands),
            1,
        )


if __name__ == "__main__":
    unittest.main()
