from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.security.token_authenticator import (
    TokenAuthenticator,
)
from app.api.permission_demo import (
    get_permission_demo_executor,
    router,
)
from app.api.query import (
    get_query_audit_logger,
    get_token_authenticator,
)
from app.application.models import QueryResult
from app.application.security_models import (
    SecurityPrincipal,
)


TOKEN = "permission_demo_token_1234567890"


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = []

    def execute_query(
        self,
        sql,
        parameters,
        max_rows=1000,
    ) -> QueryResult:
        self.calls.append(
            (sql, parameters, max_rows)
        )

        columns = [
            "customer_id",
            "institution_id",
            "rm_id",
            "customer_name",
            "phone",
            "id_card",
            "account_number",
            "aum_scaled",
            "risk_level",
            "internal_remark",
            "data_classification",
        ]

        rows = [
            [
                "DEMO-C001",
                "ORG009",
                "RM001",
                "演示客户甲",
                "13800000001",
                "DEMO-ID-00000001",
                "DEMO-ACCOUNT-000001",
                125000000,
                "低",
                "内部记录甲",
                "synthetic_permission_demo",
            ],
            [
                "DEMO-C002",
                "ORG009",
                "RM001",
                "演示客户乙",
                "13800000002",
                "DEMO-ID-00000002",
                "DEMO-ACCOUNT-000002",
                86000000,
                "中",
                "内部记录乙",
                "synthetic_permission_demo",
            ],
            [
                "DEMO-C003",
                "ORG009",
                "RM002",
                "演示客户丙",
                "13800000003",
                "DEMO-ID-00000003",
                "DEMO-ACCOUNT-000003",
                42000000,
                "高",
                "内部记录丙",
                "synthetic_permission_demo",
            ],
        ]

        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=False,
            duration_ms=1.0,
        )


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


def make_principal(
    role: str,
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id=f"user_{role}",
        display_name=role,
        role=role,
        allowed_institution_ids=(
            frozenset({"ORG009"})
            if role in {
                "institution_analyst",
                "relationship_manager",
            }
            else frozenset({"*"})
        ),
        masking_profile=(
            "none"
            if role == "admin"
            else "standard"
        ),
        authenticated=True,
        allowed_rm_ids=(
            frozenset({"RM001"})
            if role == "relationship_manager"
            else None
        ),
    )


class PermissionDemoAPITest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router)

        self.executor = FakeExecutor()
        self.audit_logger = (
            CapturingAuditLogger()
        )

        self.app.dependency_overrides[
            get_permission_demo_executor
        ] = lambda: self.executor

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
                TOKEN: make_principal(role)
            },
        )

        self.app.dependency_overrides[
            get_token_authenticator
        ] = lambda: authenticator

    def request(
        self,
        institution_id: str = "ORG009",
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
            (
                "/api/v1/security/"
                "demo-portfolio"
            ),
            params={
                "institution_id": institution_id
            },
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
            self.executor.calls,
            [],
        )

    def test_auditor_cannot_read_business_rows(
        self,
    ) -> None:
        self.configure_role("auditor")

        response = self.request()

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertEqual(
            response.json()["error"]["code"],
            "PORTFOLIO_ACCESS_DENIED",
        )
        self.assertEqual(
            self.executor.calls,
            [],
        )

    def test_institution_scope_denies_other_org(
        self,
    ) -> None:
        self.configure_role(
            "institution_analyst"
        )

        response = self.request("ORG010")

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertEqual(
            response.json()["error"]["code"],
            "ACCESS_DENIED",
        )
        self.assertEqual(
            self.executor.calls,
            [],
        )

    def test_admin_receives_all_unmasked_rows(
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
            body["source_row_count"],
            3,
        )
        self.assertEqual(
            body["row_count"],
            3,
        )
        self.assertFalse(
            body["row_scope_applied"]
        )
        self.assertIn(
            "internal_remark",
            body["columns"],
        )
        self.assertEqual(
            body["masked_columns"],
            [],
        )

    def test_rm001_receives_only_own_masked_rows(
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
            body["source_row_count"],
            3,
        )
        self.assertEqual(
            body["row_count"],
            2,
        )
        self.assertTrue(
            body["row_scope_applied"]
        )
        self.assertEqual(
            body["removed_row_count"],
            1,
        )
        self.assertTrue(
            all(
                row[
                    body["columns"].index(
                        "rm_id"
                    )
                ] == "RM001"
                for row in body["rows"]
            )
        )
        self.assertNotIn(
            "internal_remark",
            body["columns"],
        )
        self.assertIn(
            "customer_name",
            body["masked_columns"],
        )
        self.assertIn(
            "phone",
            body["masked_columns"],
        )
        self.assertEqual(
            body["data_classification"],
            "synthetic_permission_demo",
        )


if __name__ == "__main__":
    unittest.main()
