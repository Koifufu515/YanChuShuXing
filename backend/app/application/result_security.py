from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.application.models import (
    JsonScalar,
)
from app.application.security_models import (
    SecurityPrincipal,
)


ALWAYS_DENIED_COLUMNS = frozenset(
    {
        "password",
        "password_hash",
        "api_key",
        "access_token",
        "refresh_token",
        "secret",
        "private_key",
        "密码",
        "密钥",
        "访问令牌",
    }
)

PERSON_NAME_COLUMNS = frozenset(
    {
        "customer_name",
        "client_name",
        "person_name",
        "姓名",
        "客户姓名",
    }
)

PHONE_COLUMNS = frozenset(
    {
        "phone",
        "mobile",
        "phone_number",
        "mobile_number",
        "手机号",
        "手机号码",
        "联系电话",
    }
)

IDENTITY_COLUMNS = frozenset(
    {
        "id_card",
        "identity_number",
        "citizen_id",
        "身份证号",
        "证件号码",
    }
)

ACCOUNT_COLUMNS = frozenset(
    {
        "account_number",
        "account_no",
        "bank_card_number",
        "card_number",
        "银行卡号",
        "银行账号",
        "客户账号",
    }
)

EMAIL_COLUMNS = frozenset(
    {
        "email",
        "email_address",
        "电子邮箱",
        "邮箱",
    }
)

ADDRESS_COLUMNS = frozenset(
    {
        "address",
        "home_address",
        "residential_address",
        "家庭住址",
        "联系地址",
    }
)

INTERNAL_COLUMNS = frozenset(
    {
        "internal_remark",
        "risk_comment",
        "review_comment",
        "internal_tag",
        "内部备注",
        "风控备注",
        "审核意见",
    }
)

ANALYST_ROLES = frozenset(
    {
        "province_analyst",
        "institution_analyst",
    }
)


@dataclass(frozen=True)
class SecuredResult:
    columns: list[str]
    rows: list[list[JsonScalar]]
    removed_columns: list[str]
    masked_columns: list[str]


def secure_result(
    *,
    columns: list[str],
    rows: list[list[JsonScalar]],
    principal: SecurityPrincipal,
) -> SecuredResult:
    """
    根据岗位角色和脱敏策略处理表格结果。

    规则：
    1. 密码、令牌、密钥等字段始终移除；
    2. 普通分析岗位不能查看内部备注类字段；
    3. 个人标识字段按照脱敏策略处理；
    4. 机构编号、机构名称、指标、日期和值不属于
       本模块默认脱敏范围；
    5. 不修改输入列表。
    """

    if any(
        len(row) != len(columns)
        for row in rows
    ):
        raise ValueError(
            "结果行长度必须与列数量一致。"
        )

    kept_indexes: list[int] = []
    output_columns: list[str] = []
    removed_columns: list[str] = []

    for index, column in enumerate(columns):
        normalized = _normalize_column(
            column
        )

        if normalized in ALWAYS_DENIED_COLUMNS:
            removed_columns.append(column)
            continue

        if (
            principal.role in ANALYST_ROLES
            and normalized in INTERNAL_COLUMNS
        ):
            removed_columns.append(column)
            continue

        kept_indexes.append(index)
        output_columns.append(column)

    masked_columns: list[str] = []

    for index in kept_indexes:
        column = columns[index]

        if _should_mask(
            column,
            principal,
        ):
            masked_columns.append(column)

    output_rows: list[
        list[JsonScalar]
    ] = []

    for row in rows:
        secured_row: list[
            JsonScalar
        ] = []

        for index in kept_indexes:
            column = columns[index]
            value = row[index]

            if _should_mask(
                column,
                principal,
            ):
                secured_row.append(
                    _mask_value(
                        column=column,
                        value=value,
                        profile=(
                            principal
                            .masking_profile
                        ),
                    )
                )
            else:
                secured_row.append(value)

        output_rows.append(secured_row)

    return SecuredResult(
        columns=output_columns,
        rows=output_rows,
        removed_columns=removed_columns,
        masked_columns=masked_columns,
    )


def _should_mask(
    column: str,
    principal: SecurityPrincipal,
) -> bool:
    if (
        principal.masking_profile
        == "none"
    ):
        return False

    normalized = _normalize_column(
        column
    )

    return normalized in (
        PERSON_NAME_COLUMNS
        | PHONE_COLUMNS
        | IDENTITY_COLUMNS
        | ACCOUNT_COLUMNS
        | EMAIL_COLUMNS
        | ADDRESS_COLUMNS
    )


def _mask_value(
    *,
    column: str,
    value: JsonScalar,
    profile: str,
) -> JsonScalar:
    if value is None:
        return None

    text = str(value)

    if text == "":
        return ""

    if profile == "strict":
        return _stable_mask(text)

    normalized = _normalize_column(
        column
    )

    if normalized in PERSON_NAME_COLUMNS:
        return _mask_name(text)

    if normalized in PHONE_COLUMNS:
        return _mask_phone(text)

    if normalized in IDENTITY_COLUMNS:
        return _mask_identity(text)

    if normalized in ACCOUNT_COLUMNS:
        return _mask_account(text)

    if normalized in EMAIL_COLUMNS:
        return _mask_email(text)

    if normalized in ADDRESS_COLUMNS:
        return _mask_address(text)

    return _stable_mask(text)


def _normalize_column(
    column: str,
) -> str:
    return re.sub(
        r"[\s\-]+",
        "_",
        str(column).strip().lower(),
    )


def _mask_name(
    value: str,
) -> str:
    if len(value) <= 1:
        return "*"

    return (
        value[0]
        + "*" * (len(value) - 1)
    )


def _mask_phone(
    value: str,
) -> str:
    if len(value) < 7:
        return _stable_mask(value)

    return (
        value[:3]
        + "****"
        + value[-4:]
    )


def _mask_identity(
    value: str,
) -> str:
    if len(value) < 8:
        return _stable_mask(value)

    return (
        value[:3]
        + "*" * (len(value) - 7)
        + value[-4:]
    )


def _mask_account(
    value: str,
) -> str:
    if len(value) < 8:
        return _stable_mask(value)

    return (
        value[:4]
        + "*" * (len(value) - 8)
        + value[-4:]
    )


def _mask_email(
    value: str,
) -> str:
    local, separator, domain = (
        value.partition("@")
    )

    if not separator:
        return _stable_mask(value)

    visible = (
        local[:1]
        if local
        else ""
    )

    return (
        visible
        + "***@"
        + domain
    )


def _mask_address(
    value: str,
) -> str:
    if len(value) <= 6:
        return _stable_mask(value)

    return (
        value[:6]
        + "****"
    )


def _stable_mask(
    value: str,
) -> str:
    digest = hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:10]

    return f"MASKED-{digest}"
