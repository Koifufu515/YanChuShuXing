from __future__ import annotations

import json
import unittest

from app.adapters.security.token_authenticator import (
    AuthenticationConfigurationError,
    AuthenticationRequiredError,
    InvalidAuthenticationError,
    TokenAuthenticator,
)


TOKEN = "test_token_1234567890abcdef"


def environment(
    *,
    required: bool = True,
) -> dict[str, str]:
    return {
        "BANKINSIGHT_AUTH_REQUIRED": (
            "1" if required else "0"
        ),
        "BANKINSIGHT_AUTH_TOKENS_JSON": json.dumps(
            {
                TOKEN: {
                    "subject_id": "user_org009",
                    "display_name": "I市机构分析岗",
                    "role": "institution_analyst",
                    "allowed_institution_ids": [
                        "ORG009"
                    ],
                    "masking_profile": "standard",
                }
            },
            ensure_ascii=False,
        ),
    }


class TokenAuthenticatorTest(unittest.TestCase):
    def test_optional_mode_allows_legacy_identity(
        self,
    ) -> None:
        authenticator = TokenAuthenticator.from_environment(
            environment(required=False)
        )

        principal = authenticator.authenticate(
            authorization=None,
            claimed_user_id="legacy_user",
        )

        self.assertFalse(principal.authenticated)
        self.assertEqual(
            principal.subject_id,
            "legacy_user",
        )

    def test_required_mode_rejects_missing_token(
        self,
    ) -> None:
        authenticator = TokenAuthenticator.from_environment(
            environment()
        )

        with self.assertRaises(
            AuthenticationRequiredError
        ):
            authenticator.authenticate(
                authorization=None,
                claimed_user_id="forged_user",
            )

    def test_invalid_token_is_rejected(
        self,
    ) -> None:
        authenticator = TokenAuthenticator.from_environment(
            environment()
        )

        with self.assertRaises(
            InvalidAuthenticationError
        ):
            authenticator.authenticate(
                authorization=(
                    "Bearer invalid_token_1234567890"
                ),
                claimed_user_id="forged_user",
            )

    def test_token_identity_overrides_claimed_user(
        self,
    ) -> None:
        authenticator = TokenAuthenticator.from_environment(
            environment()
        )

        principal = authenticator.authenticate(
            authorization=f"Bearer {TOKEN}",
            claimed_user_id="forged_user",
        )

        self.assertTrue(principal.authenticated)
        self.assertEqual(
            principal.subject_id,
            "user_org009",
        )
        self.assertEqual(
            principal.role,
            "institution_analyst",
        )
        self.assertEqual(
            principal.allowed_institution_ids,
            frozenset({"ORG009"}),
        )

    def test_relationship_manager_receives_row_scope(
        self,
    ) -> None:
        token = (
            "relationship_manager_token_123456"
        )
        authenticator = (
            TokenAuthenticator.from_environment(
                {
                    "BANKINSIGHT_AUTH_REQUIRED": "1",
                    "BANKINSIGHT_AUTH_TOKENS_JSON": (
                        json.dumps(
                            {
                                token: {
                                    "subject_id": "rm001",
                                    "display_name": (
                                        "RM001客户经理"
                                    ),
                                    "role": (
                                        "relationship_manager"
                                    ),
                                    "allowed_institution_ids": [
                                        "ORG009"
                                    ],
                                    "allowed_rm_ids": [
                                        "RM001"
                                    ],
                                    "masking_profile": (
                                        "standard"
                                    ),
                                }
                            },
                            ensure_ascii=False,
                        )
                    ),
                }
            )
        )

        principal = authenticator.authenticate(
            authorization=f"Bearer {token}",
            claimed_user_id="forged_user",
        )

        self.assertEqual(
            principal.role,
            "relationship_manager",
        )
        self.assertEqual(
            principal.allowed_institution_ids,
            frozenset({"ORG009"}),
        )
        self.assertEqual(
            principal.allowed_rm_ids,
            frozenset({"RM001"}),
        )

    def test_relationship_manager_rejects_wildcard_row_scope(
        self,
    ) -> None:
        token = (
            "relationship_manager_token_654321"
        )

        with self.assertRaises(
            AuthenticationConfigurationError
        ):
            TokenAuthenticator.from_environment(
                {
                    "BANKINSIGHT_AUTH_REQUIRED": "1",
                    "BANKINSIGHT_AUTH_TOKENS_JSON": (
                        json.dumps(
                            {
                                token: {
                                    "subject_id": "rm_all",
                                    "display_name": (
                                        "错误客户经理配置"
                                    ),
                                    "role": (
                                        "relationship_manager"
                                    ),
                                    "allowed_institution_ids": [
                                        "ORG009"
                                    ],
                                    "allowed_rm_ids": "*",
                                    "masking_profile": (
                                        "standard"
                                    ),
                                }
                            },
                            ensure_ascii=False,
                        )
                    ),
                }
            )

    def test_required_mode_rejects_empty_configuration(
        self,
    ) -> None:
        with self.assertRaises(
            AuthenticationConfigurationError
        ):
            TokenAuthenticator.from_environment(
                {
                    "BANKINSIGHT_AUTH_REQUIRED": "1",
                    "BANKINSIGHT_AUTH_TOKENS_JSON": "{}",
                }
            )


if __name__ == "__main__":
    unittest.main()
