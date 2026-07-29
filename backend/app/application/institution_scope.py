from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.application.security_models import (
    SecurityPrincipal,
)
from app.application.errors import ApplicationError


INSTITUTION_ID_PATTERN = re.compile(
    r"^ORG\d{3}$"
)


class InstitutionAccessDeniedError(
    ApplicationError
):
    """查询计划超出当前用户的机构数据范围。"""

    code = "ACCESS_DENIED"


@dataclass(frozen=True)
class InstitutionAccessDecision:
    allowed: bool
    referenced_institution_ids: frozenset[str]
    unauthorized_institution_ids: frozenset[str]
    reason: str


def extract_institution_ids(
    query_plan: object,
) -> frozenset[str]:
    """
    从查询计划的任意嵌套结构中提取机构编号。

    只识别完整符合 ORG + 三位数字格式的字符串，
    不根据自然语言机构名称猜测机构范围。
    """

    institution_ids: set[str] = set()

    def walk(
        value: object,
    ) -> None:
        if isinstance(value, str):
            if INSTITUTION_ID_PATTERN.fullmatch(
                value
            ):
                institution_ids.add(value)
            return

        if isinstance(value, Mapping):
            for item in value.values():
                walk(item)
            return

        if isinstance(
            value,
            (
                list,
                tuple,
                set,
                frozenset,
            ),
        ):
            for item in value:
                walk(item)

    walk(query_plan)

    return frozenset(institution_ids)


def evaluate_institution_access(
    query_plan: object,
    principal: SecurityPrincipal,
) -> InstitutionAccessDecision:
    """
    评估查询计划是否位于当前身份的机构权限范围内。

    安全规则：
    1. allowed_institution_ids 为 None：
       兼容模式，暂不进行机构范围限制。
    2. 授权范围包含 "*"：
       允许访问全部机构。
    3. 受限身份的查询计划没有明确机构：
       默认拒绝，避免范围不明的查询被执行。
    4. 查询计划包含任一未授权机构：
       拒绝整个查询，不返回部分结果。
    """

    referenced = extract_institution_ids(
        query_plan
    )

    allowed_scope = (
        principal.allowed_institution_ids
    )

    if allowed_scope is None:
        return InstitutionAccessDecision(
            allowed=True,
            referenced_institution_ids=(
                referenced
            ),
            unauthorized_institution_ids=(
                frozenset()
            ),
            reason=(
                "兼容模式未启用机构范围限制。"
            ),
        )

    if "*" in allowed_scope:
        return InstitutionAccessDecision(
            allowed=True,
            referenced_institution_ids=(
                referenced
            ),
            unauthorized_institution_ids=(
                frozenset()
            ),
            reason=(
                "当前身份具有全省机构访问范围。"
            ),
        )

    if not referenced:
        return InstitutionAccessDecision(
            allowed=False,
            referenced_institution_ids=(
                frozenset()
            ),
            unauthorized_institution_ids=(
                frozenset()
            ),
            reason=(
                "受限身份的查询计划未明确机构范围。"
            ),
        )

    unauthorized = (
        referenced - allowed_scope
    )

    if unauthorized:
        return InstitutionAccessDecision(
            allowed=False,
            referenced_institution_ids=(
                referenced
            ),
            unauthorized_institution_ids=(
                unauthorized
            ),
            reason=(
                "查询计划包含当前身份无权访问的机构。"
            ),
        )

    return InstitutionAccessDecision(
        allowed=True,
        referenced_institution_ids=(
            referenced
        ),
        unauthorized_institution_ids=(
            frozenset()
        ),
        reason=(
            "查询计划位于当前身份授权机构范围内。"
        ),
    )


def require_institution_access(
    query_plan: object,
    principal: SecurityPrincipal,
) -> InstitutionAccessDecision:
    """
    返回访问决策；不允许时抛出统一机构权限异常。
    """

    decision = evaluate_institution_access(
        query_plan,
        principal,
    )

    if not decision.allowed:
        raise InstitutionAccessDeniedError(
            decision.reason
        )

    return decision
