from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.security.token_authenticator import (
    TokenAuthenticator,
)
from app.api.query import (
    get_query_audit_logger,
    get_token_authenticator,
)
from app.api.session import router
from app.application.security_models import (
    SecurityPrincipal,
)


TOKEN = "session_profile_token_1234567890"


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


def principal(
    role: str,
) -> SecurityPrincipal:
    institution_scope = (
        frozenset({"ORG009"})
        if role in {
            "institution_analyst",
            "relationship_manager",
        }
        else frozenset({"*"})
    )

    return SecurityPrincipal(
        subject_id=f"user_{role}",
        display_name={
            "admin": "系统管理员",
            "relationship_manager": (
                "RM001客户经理"
            ),
            "auditor": "安全审计岗",
        }.get(role, role),
        role=role,
        allowed_institution_ids=(
            institution_scope
        ),
        masking_profile=(
            "none"
            if role == "admin"
            else "standard"
        ),
        authenticated=True,
        allowed_rm_ids=(
            frozenset({"RM001"})
            if role
            == "relationship_manager"
            else None
        ),
    )


class SessionAPITest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router)

        self.audit_logger = (
            CapturingAuditLogger()
        )

        self.app.dependency_overrides[
            get_query_audit_logger
        ] = lambda: self.audit_logger

        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()
        self.client.close()

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

        self.app.dependency_overrides[
            get_token_authenticator
        ] = lambda: authenticator

    def request(
        self,
        token: str | None = TOKEN,
    ):
        headers = (
            {
                "Authorization": (
                    f"Bearer {token}"
                )
            }
            if token is not None
            else {}
        )

        return self.client.get(
            "/api/v1/session/me",
            headers=headers,
        )

    def test_missing_token_returns_401(
        self,
    ) -> None:
        self.configure_role("admin")

        response = self.request(token=None)

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

    def test_invalid_token_returns_401(
        self,
    ) -> None:
        self.configure_role("admin")

        response = self.request(
            "invalid_session_token_12345"
        )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            response.json()["error"]["code"],
            "INVALID_AUTHENTICATION",
        )

    def test_admin_profile_has_global_access(
        self,
    ) -> None:
        self.configure_role("admin")

        response = self.request()

        self.assertEqual(
            response.status_code,
            200,
        )

        body = response.json()

        self.assertEqual(
            body["subject_id"],
            "user_admin",
        )
        self.assertEqual(
            body["role_label"],
            "系统管理员",
        )
        self.assertEqual(
            body["masking_profile"],
            "none",
        )
        self.assertEqual(
            body["institution_scope"],
            {
                "enforced": True,
                "all_access": True,
                "ids": [],
            },
        )
        self.assertEqual(
            body[
                "relationship_manager_scope"
            ],
            {
                "enforced": False,
                "all_access": False,
                "ids": [],
            },
        )
        self.assertTrue(
            body["capabilities"][
                "can_view_permission_demo"
            ]
        )
        self.assertTrue(
            body["capabilities"][
                "can_view_security_alerts"
            ]
        )
        self.assertFalse(
            body["capabilities"][
                "row_scope_active"
            ]
        )

    def test_relationship_manager_profile_exposes_scopes(
        self,
    ) -> None:
        self.configure_role(
            "relationship_manager"
        )

        response = self.request()

        self.assertEqual(
            response.status_code,
            200,
        )

        body = response.json()

        self.assertEqual(
            body["role_label"],
            "客户经理",
        )
        self.assertEqual(
            body["institution_scope"]["ids"],
            ["ORG009"],
        )
        self.assertEqual(
            body[
                "relationship_manager_scope"
            ]["ids"],
            ["RM001"],
        )
        self.assertTrue(
            body["capabilities"][
                "row_scope_active"
            ]
        )
        self.assertTrue(
            body["capabilities"][
                "can_view_permission_demo"
            ]
        )
        self.assertFalse(
            body["capabilities"][
                "can_view_security_alerts"
            ]
        )

    def test_auditor_profile_matches_alert_permissions(
        self,
    ) -> None:
        self.configure_role("auditor")

        response = self.request()

        self.assertEqual(
            response.status_code,
            200,
        )

        body = response.json()

        self.assertEqual(
            body["role_label"],
            "安全审计岗",
        )
        self.assertFalse(
            body["capabilities"][
                "can_view_permission_demo"
            ]
        )
        self.assertTrue(
            body["capabilities"][
                "can_view_security_alerts"
            ]
        )

    def test_successful_lookup_is_audited(
        self,
    ) -> None:
        self.configure_role(
            "relationship_manager"
        )

        response = self.request()

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            self.audit_logger.events[-1]
            .security_action,
            "session_profile_read",
        )
        self.assertEqual(
            self.audit_logger.events[-1]
            .actor_role,
            "relationship_manager",
        )


if __name__ == "__main__":
    unittest.main()
