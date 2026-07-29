from __future__ import annotations

import unittest

from fastapi.testclient import (
    TestClient,
)

from app.adapters.security.token_authenticator import (
    SecurityPrincipal,
    TokenAuthenticator,
)
from app.api.query import (
    get_query_pipeline,
    get_token_authenticator,
)
from app.application.models import (
    QueryOutcome,
)
from app.main import app


TOKEN = (
    "test_token_1234567890abcdef"
)


def authenticated_principal(
) -> SecurityPrincipal:
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


class APIAuthenticationTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.pipeline = CapturingPipeline()

        self.authenticator = (
            TokenAuthenticator(
                authentication_required=True,
                principals_by_token={
                    TOKEN: (
                        authenticated_principal()
                    )
                },
            )
        )

        app.dependency_overrides[
            get_query_pipeline
        ] = lambda: self.pipeline

        app.dependency_overrides[
            get_token_authenticator
        ] = lambda: self.authenticator

        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()

    def test_missing_token_returns_common_401_shape(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/query",
            json={
                "question": (
                    "查询不良贷款率"
                ),
                "user_id": "forged_user",
            },
        )

        body = response.json()

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            body["error"]["code"],
            "AUTHENTICATION_REQUIRED",
        )
        self.assertEqual(
            response.headers.get(
                "www-authenticate"
            ),
            "Bearer",
        )
        self.assertEqual(
            self.pipeline.commands,
            [],
        )

    def test_invalid_token_returns_401(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/query",
            headers={
                "Authorization": (
                    "Bearer invalid_token_"
                    "1234567890"
                )
            },
            json={
                "question": (
                    "查询不良贷款率"
                ),
                "user_id": "forged_user",
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            response.json()["error"][
                "code"
            ],
            "INVALID_AUTHENTICATION",
        )
        self.assertEqual(
            self.pipeline.commands,
            [],
        )

    def test_valid_token_uses_authenticated_identity(
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
                "question": (
                    "查询不良贷款率"
                ),
                "user_id": "forged_user",
                "conversation_id": (
                    "auth_test"
                ),
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

        command = (
            self.pipeline.commands[0]
        )

        self.assertEqual(
            command.user_id,
            "user_org009",
        )
        self.assertNotEqual(
            command.user_id,
            "forged_user",
        )
        self.assertEqual(
            command.conversation_id,
            "auth_test",
        )
        self.assertIsNotNone(
            command.security_principal
        )
        self.assertEqual(
            command.security_principal.subject_id,
            "user_org009",
        )
        self.assertEqual(
            command.security_principal.role,
            "institution_analyst",
        )
        self.assertEqual(
            command.security_principal.allowed_institution_ids,
            frozenset({"ORG009"}),
        )

    def test_ask_alias_uses_same_authentication(
        self,
    ) -> None:
        response = self.client.post(
            "/api/v1/ask",
            headers={
                "Authorization": (
                    f"Bearer {TOKEN}"
                )
            },
            json={
                "question": (
                    "查询不良贷款率"
                ),
                "user_id": "forged_user",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            self.pipeline.commands[0]
            .user_id,
            "user_org009",
        )


if __name__ == "__main__":
    unittest.main()
