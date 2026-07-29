from __future__ import annotations

import unittest

from app.adapters.security.institution_scope import (
    InstitutionAccessDeniedError,
    evaluate_institution_access,
    extract_institution_ids,
    require_institution_access,
)
from app.adapters.security.token_authenticator import (
    SecurityPrincipal,
)


def institution_principal(
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


def province_principal(
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id="province_user",
        display_name="全省经营分析岗",
        role="province_analyst",
        allowed_institution_ids=(
            frozenset({"*"})
        ),
        masking_profile="standard",
        authenticated=True,
    )


def legacy_principal(
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id="legacy_user",
        display_name="兼容模式用户",
        role="legacy",
        allowed_institution_ids=None,
        masking_profile="none",
        authenticated=False,
    )


class InstitutionScopeTest(
    unittest.TestCase
):
    def test_extracts_unique_nested_institution_ids(
        self,
    ) -> None:
        query_plan = {
            "operations": [
                {
                    "operator_id": "OP001",
                    "params": {
                        "institution_id": (
                            "ORG009"
                        ),
                        "metric_id": "ZB013",
                    },
                },
                {
                    "operator_id": "OP019",
                    "targets": [
                        {
                            "institution_id": (
                                "ORG010"
                            )
                        },
                        {
                            "institution_id": (
                                "ORG009"
                            )
                        },
                    ],
                },
            ],
            "description": (
                "ORG009-extra不是合法机构编号"
            ),
        }

        self.assertEqual(
            extract_institution_ids(
                query_plan
            ),
            frozenset(
                {
                    "ORG009",
                    "ORG010",
                }
            ),
        )

    def test_legacy_mode_is_temporarily_allowed(
        self,
    ) -> None:
        decision = (
            evaluate_institution_access(
                {
                    "operations": [
                        {
                            "params": {
                                "institution_id": (
                                    "ORG013"
                                )
                            }
                        }
                    ]
                },
                legacy_principal(),
            )
        )

        self.assertTrue(
            decision.allowed
        )
        self.assertEqual(
            decision
            .unauthorized_institution_ids,
            frozenset(),
        )

    def test_province_scope_allows_all_institutions(
        self,
    ) -> None:
        decision = (
            evaluate_institution_access(
                {
                    "operations": [
                        {
                            "params": {
                                "institution_ids": [
                                    "ORG001",
                                    "ORG013",
                                ]
                            }
                        }
                    ]
                },
                province_principal(),
            )
        )

        self.assertTrue(
            decision.allowed
        )

    def test_own_institution_is_allowed(
        self,
    ) -> None:
        decision = (
            require_institution_access(
                {
                    "operations": [
                        {
                            "params": {
                                "institution_id": (
                                    "ORG009"
                                )
                            }
                        }
                    ]
                },
                institution_principal(),
            )
        )

        self.assertTrue(
            decision.allowed
        )
        self.assertEqual(
            decision
            .referenced_institution_ids,
            frozenset({"ORG009"}),
        )

    def test_other_institution_is_denied(
        self,
    ) -> None:
        with self.assertRaises(
            InstitutionAccessDeniedError
        ):
            require_institution_access(
                {
                    "operations": [
                        {
                            "params": {
                                "institution_id": (
                                    "ORG013"
                                )
                            }
                        }
                    ]
                },
                institution_principal(),
            )

    def test_mixed_authorized_and_unauthorized_scope_is_denied(
        self,
    ) -> None:
        decision = (
            evaluate_institution_access(
                {
                    "operations": [
                        {
                            "params": {
                                "institution_ids": [
                                    "ORG009",
                                    "ORG010",
                                ]
                            }
                        }
                    ]
                },
                institution_principal(),
            )
        )

        self.assertFalse(
            decision.allowed
        )
        self.assertEqual(
            decision
            .unauthorized_institution_ids,
            frozenset({"ORG010"}),
        )

    def test_restricted_identity_fails_closed_without_institution(
        self,
    ) -> None:
        decision = (
            evaluate_institution_access(
                {
                    "operations": [
                        {
                            "params": {
                                "metric_id": (
                                    "ZB013"
                                )
                            }
                        }
                    ]
                },
                institution_principal(),
            )
        )

        self.assertFalse(
            decision.allowed
        )
        self.assertEqual(
            decision
            .referenced_institution_ids,
            frozenset(),
        )


if __name__ == "__main__":
    unittest.main()
