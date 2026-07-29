from __future__ import annotations

import re
from dataclasses import dataclass

from app.application.errors import ApplicationError
from app.application.models import JsonScalar
from app.application.security_models import (
    SecurityPrincipal,
)


ROW_SCOPE_COLUMN_ALIASES = frozenset(
    {
        "rm_id",
        "relationship_manager_id",
        "customer_manager_id",
        "客户经理编号",
        "客户经理id",
    }
)


class RowScopeEnforcementError(ApplicationError):
    """无法安全执行客户经理行级权限。"""

    code = "ROW_SCOPE_ENFORCEMENT_FAILED"


@dataclass(frozen=True)
class RowScopedResult:
    columns: list[str]
    rows: list[list[JsonScalar]]
    applied: bool
    scope_column: str | None
    removed_row_count: int


def apply_relationship_manager_scope(
    *,
    columns: list[str],
    rows: list[list[JsonScalar]],
    principal: SecurityPrincipal,
) -> RowScopedResult:
    """
    按身份绑定的客户经理编号过滤结果行。

    规则：
    1. allowed_rm_ids 为 None：该身份不启用客户经理行级限制；
    2. allowed_rm_ids 包含 "*"：允许查看全部客户经理记录；
    3. 受限身份的结果必须包含客户经理范围字段；
    4. 只保留 rm_id 位于授权集合中的记录；
    5. 不修改调用方传入的 columns 和 rows。
    """
    _validate_rows(
        columns=columns,
        rows=rows,
    )

    allowed_scope = principal.allowed_rm_ids

    if (
        allowed_scope is None
        or "*" in allowed_scope
    ):
        return RowScopedResult(
            columns=list(columns),
            rows=[
                list(row)
                for row in rows
            ],
            applied=False,
            scope_column=None,
            removed_row_count=0,
        )

    scope_index = _find_scope_column(columns)

    if scope_index is None:
        raise RowScopeEnforcementError(
            "受限身份的查询结果缺少客户经理范围字段。"
        )

    scoped_rows = [
        list(row)
        for row in rows
        if _scope_value(row[scope_index])
        in allowed_scope
    ]

    return RowScopedResult(
        columns=list(columns),
        rows=scoped_rows,
        applied=True,
        scope_column=columns[scope_index],
        removed_row_count=(
            len(rows) - len(scoped_rows)
        ),
    )


def _find_scope_column(
    columns: list[str],
) -> int | None:
    for index, column in enumerate(columns):
        if (
            _normalize_column(column)
            in ROW_SCOPE_COLUMN_ALIASES
        ):
            return index

    return None


def _validate_rows(
    *,
    columns: list[str],
    rows: list[list[JsonScalar]],
) -> None:
    if any(
        len(row) != len(columns)
        for row in rows
    ):
        raise ValueError(
            "结果行长度必须与列数量一致。"
        )


def _scope_value(
    value: JsonScalar,
) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _normalize_column(
    column: str,
) -> str:
    return re.sub(
        r"[\s\-]+",
        "_",
        str(column).strip().lower(),
    )
