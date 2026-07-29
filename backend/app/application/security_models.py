from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityPrincipal:
    """
    已解析的调用身份。

    该模型只描述身份和授权范围，
    不负责读取令牌、校验请求或执行权限判断。
    """

    subject_id: str
    display_name: str
    role: str
    allowed_institution_ids: frozenset[str] | None
    masking_profile: str
    authenticated: bool
    allowed_rm_ids: frozenset[str] | None = None
