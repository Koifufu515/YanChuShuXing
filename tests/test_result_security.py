from __future__ import annotations

import unittest

from app.application.result_security import (
    secure_result,
)
from app.application.security_models import (
    SecurityPrincipal,
)


def principal(
    *,
    role: str,
    profile: str,
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id="test_user",
        display_name="测试用户",
        role=role,
        allowed_institution_ids=(
            frozenset({"ORG009"})
        ),
        masking_profile=profile,
        authenticated=True,
    )


class ResultSecurityTest(
    unittest.TestCase
):
    def test_always_removes_secret_columns(
        self,
    ) -> None:
        result = secure_result(
            columns=[
                "机构名称",
                "api_key",
                "指标值",
            ],
            rows=[
                [
                    "江苏省I市农商行",
                    "secret-value",
                    1.46,
                ]
            ],
            principal=principal(
                role="admin",
                profile="none",
            ),
        )

        self.assertEqual(
            result.columns,
            ["机构名称", "指标值"],
        )
        self.assertEqual(
            result.rows,
            [
                [
                    "江苏省I市农商行",
                    1.46,
                ]
            ],
        )
        self.assertEqual(
            result.removed_columns,
            ["api_key"],
        )

    def test_analyst_cannot_view_internal_comment(
        self,
    ) -> None:
        result = secure_result(
            columns=[
                "机构名称",
                "内部备注",
            ],
            rows=[
                [
                    "江苏省I市农商行",
                    "内部审核信息",
                ]
            ],
            principal=principal(
                role=(
                    "institution_analyst"
                ),
                profile="standard",
            ),
        )

        self.assertEqual(
            result.columns,
            ["机构名称"],
        )
        self.assertEqual(
            result.removed_columns,
            ["内部备注"],
        )

    def test_admin_can_view_internal_comment(
        self,
    ) -> None:
        result = secure_result(
            columns=["内部备注"],
            rows=[["内部审核信息"]],
            principal=principal(
                role="admin",
                profile="none",
            ),
        )

        self.assertEqual(
            result.rows,
            [["内部审核信息"]],
        )

    def test_standard_profile_masks_personal_fields(
        self,
    ) -> None:
        result = secure_result(
            columns=[
                "客户姓名",
                "手机号",
                "身份证号",
                "银行账号",
                "邮箱",
            ],
            rows=[
                [
                    "张三",
                    "13812345678",
                    "320101199001011234",
                    "6222021234567890",
                    "zhangsan@example.com",
                ]
            ],
            principal=principal(
                role="auditor",
                profile="standard",
            ),
        )

        self.assertEqual(
            result.rows[0][0],
            "张*",
        )
        self.assertEqual(
            result.rows[0][1],
            "138****5678",
        )
        self.assertTrue(
            result.rows[0][2].startswith(
                "320"
            )
        )
        self.assertTrue(
            result.rows[0][2].endswith(
                "1234"
            )
        )
        self.assertTrue(
            result.rows[0][3].startswith(
                "6222"
            )
        )
        self.assertTrue(
            result.rows[0][3].endswith(
                "7890"
            )
        )
        self.assertEqual(
            result.rows[0][4],
            "z***@example.com",
        )

    def test_strict_profile_uses_stable_irreversible_mask(
        self,
    ) -> None:
        first = secure_result(
            columns=["客户姓名"],
            rows=[["张三"]],
            principal=principal(
                role="auditor",
                profile="strict",
            ),
        )

        second = secure_result(
            columns=["客户姓名"],
            rows=[["张三"]],
            principal=principal(
                role="auditor",
                profile="strict",
            ),
        )

        self.assertEqual(
            first.rows,
            second.rows,
        )
        self.assertTrue(
            str(first.rows[0][0]).startswith(
                "MASKED-"
            )
        )
        self.assertNotIn(
            "张三",
            str(first.rows[0][0]),
        )

    def test_none_profile_does_not_mask_personal_fields(
        self,
    ) -> None:
        result = secure_result(
            columns=[
                "客户姓名",
                "手机号",
            ],
            rows=[
                [
                    "张三",
                    "13812345678",
                ]
            ],
            principal=principal(
                role="admin",
                profile="none",
            ),
        )

        self.assertEqual(
            result.rows,
            [
                [
                    "张三",
                    "13812345678",
                ]
            ],
        )
        self.assertEqual(
            result.masked_columns,
            [],
        )

    def test_business_metric_fields_are_not_masked(
        self,
    ) -> None:
        result = secure_result(
            columns=[
                "机构编号",
                "机构名称",
                "指标名称",
                "日期",
                "指标值",
                "单位",
            ],
            rows=[
                [
                    "ORG009",
                    "江苏省I市农商行",
                    "不良贷款率",
                    "2025-11-30",
                    1.46,
                    "%",
                ]
            ],
            principal=principal(
                role=(
                    "institution_analyst"
                ),
                profile="standard",
            ),
        )

        self.assertEqual(
            result.rows[0],
            [
                "ORG009",
                "江苏省I市农商行",
                "不良贷款率",
                "2025-11-30",
                1.46,
                "%",
            ],
        )

    def test_rejects_mismatched_row_length(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            secure_result(
                columns=["机构", "值"],
                rows=[["ORG009"]],
                principal=principal(
                    role="admin",
                    profile="none",
                ),
            )


if __name__ == "__main__":
    unittest.main()
