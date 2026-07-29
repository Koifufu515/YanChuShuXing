from __future__ import annotations

import unittest

from app.application.row_scope import (
    RowScopeEnforcementError,
    apply_relationship_manager_scope,
)
from app.application.security_models import (
    SecurityPrincipal,
)


def principal(
    *,
    role: str = "relationship_manager",
    allowed_rm_ids: frozenset[str] | None,
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id="test_user",
        display_name="测试用户",
        role=role,
        allowed_institution_ids=(
            frozenset({"ORG009"})
        ),
        masking_profile="standard",
        authenticated=True,
        allowed_rm_ids=allowed_rm_ids,
    )


class RowScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.columns = [
            "customer_id",
            "institution_id",
            "rm_id",
            "customer_name",
        ]
        self.rows = [
            [
                "DEMO-C001",
                "ORG009",
                "RM001",
                "演示客户甲",
            ],
            [
                "DEMO-C002",
                "ORG009",
                "RM001",
                "演示客户乙",
            ],
            [
                "DEMO-C003",
                "ORG009",
                "RM002",
                "演示客户丙",
            ],
        ]

    def test_unrestricted_identity_receives_all_rows(
        self,
    ) -> None:
        result = apply_relationship_manager_scope(
            columns=self.columns,
            rows=self.rows,
            principal=principal(
                role="admin",
                allowed_rm_ids=None,
            ),
        )

        self.assertFalse(result.applied)
        self.assertEqual(
            result.rows,
            self.rows,
        )
        self.assertEqual(
            result.removed_row_count,
            0,
        )
        self.assertIsNone(result.scope_column)

    def test_relationship_manager_only_receives_authorized_rows(
        self,
    ) -> None:
        result = apply_relationship_manager_scope(
            columns=self.columns,
            rows=self.rows,
            principal=principal(
                allowed_rm_ids=(
                    frozenset({"RM001"})
                ),
            ),
        )

        self.assertTrue(result.applied)
        self.assertEqual(
            result.scope_column,
            "rm_id",
        )
        self.assertEqual(
            result.removed_row_count,
            1,
        )
        self.assertEqual(
            [
                row[0]
                for row in result.rows
            ],
            [
                "DEMO-C001",
                "DEMO-C002",
            ],
        )
        self.assertTrue(
            all(
                row[2] == "RM001"
                for row in result.rows
            )
        )

    def test_multiple_authorized_managers_are_supported(
        self,
    ) -> None:
        result = apply_relationship_manager_scope(
            columns=self.columns,
            rows=self.rows,
            principal=principal(
                allowed_rm_ids=frozenset(
                    {
                        "RM001",
                        "RM002",
                    }
                ),
            ),
        )

        self.assertEqual(
            len(result.rows),
            3,
        )
        self.assertEqual(
            result.removed_row_count,
            0,
        )

    def test_empty_scope_returns_no_rows(
        self,
    ) -> None:
        result = apply_relationship_manager_scope(
            columns=self.columns,
            rows=self.rows,
            principal=principal(
                allowed_rm_ids=frozenset(),
            ),
        )

        self.assertTrue(result.applied)
        self.assertEqual(
            result.rows,
            [],
        )
        self.assertEqual(
            result.removed_row_count,
            3,
        )

    def test_limited_identity_fails_closed_without_scope_column(
        self,
    ) -> None:
        with self.assertRaises(
            RowScopeEnforcementError
        ):
            apply_relationship_manager_scope(
                columns=[
                    "customer_id",
                    "customer_name",
                ],
                rows=[
                    [
                        "DEMO-C001",
                        "演示客户甲",
                    ]
                ],
                principal=principal(
                    allowed_rm_ids=(
                        frozenset({"RM001"})
                    ),
                ),
            )

    def test_chinese_scope_column_is_supported(
        self,
    ) -> None:
        result = apply_relationship_manager_scope(
            columns=[
                "客户编号",
                "客户经理编号",
            ],
            rows=[
                [
                    "DEMO-C001",
                    "RM001",
                ],
                [
                    "DEMO-C003",
                    "RM002",
                ],
            ],
            principal=principal(
                allowed_rm_ids=(
                    frozenset({"RM001"})
                ),
            ),
        )

        self.assertEqual(
            result.rows,
            [
                [
                    "DEMO-C001",
                    "RM001",
                ]
            ],
        )
        self.assertEqual(
            result.scope_column,
            "客户经理编号",
        )

    def test_input_rows_are_not_modified(
        self,
    ) -> None:
        original_rows = [
            list(row)
            for row in self.rows
        ]

        result = apply_relationship_manager_scope(
            columns=self.columns,
            rows=self.rows,
            principal=principal(
                allowed_rm_ids=(
                    frozenset({"RM001"})
                ),
            ),
        )

        result.rows[0][0] = "CHANGED"

        self.assertEqual(
            self.rows,
            original_rows,
        )

    def test_rejects_mismatched_row_length(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            apply_relationship_manager_scope(
                columns=[
                    "customer_id",
                    "rm_id",
                ],
                rows=[
                    ["DEMO-C001"]
                ],
                principal=principal(
                    allowed_rm_ids=(
                        frozenset({"RM001"})
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
