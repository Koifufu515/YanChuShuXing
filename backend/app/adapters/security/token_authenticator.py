from __future__ import annotations

import hmac
import json
import os
from typing import Mapping

from app.application.security_models import SecurityPrincipal


VALID_ROLES = {
    "admin",
    "province_analyst",
    "institution_analyst",
    "auditor",
}


class AuthenticationError(Exception):
    """认证错误基类。"""


class AuthenticationRequiredError(AuthenticationError):
    """缺少必须的认证信息。"""


class InvalidAuthenticationError(AuthenticationError):
    """认证信息格式错误或令牌无效。"""


class AuthenticationConfigurationError(AuthenticationError):
    """认证配置错误。"""


class TokenAuthenticator:
    def __init__(
        self,
        *,
        authentication_required: bool,
        principals_by_token: Mapping[str, SecurityPrincipal],
    ) -> None:
        self.authentication_required = authentication_required
        self.principals_by_token = dict(principals_by_token)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "TokenAuthenticator":
        env = environment if environment is not None else os.environ

        required = _parse_boolean(
            env.get("BANKINSIGHT_AUTH_REQUIRED", "0")
        )

        raw = env.get(
            "BANKINSIGHT_AUTH_TOKENS_JSON",
            "{}",
        )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthenticationConfigurationError(
                "认证令牌配置不是合法JSON。"
            ) from exc

        if not isinstance(payload, dict):
            raise AuthenticationConfigurationError(
                "认证令牌配置顶层必须是JSON对象。"
            )

        principals: dict[str, SecurityPrincipal] = {}

        for token, item in payload.items():
            if not isinstance(token, str) or len(token) < 16:
                raise AuthenticationConfigurationError(
                    "访问令牌至少需要16个字符。"
                )

            if not isinstance(item, dict):
                raise AuthenticationConfigurationError(
                    "令牌对应的身份配置必须是JSON对象。"
                )

            subject_id = str(
                item.get("subject_id", "")
            ).strip()
            display_name = str(
                item.get("display_name", subject_id)
            ).strip()
            role = str(
                item.get("role", "")
            ).strip()

            if not subject_id or not display_name:
                raise AuthenticationConfigurationError(
                    "身份配置缺少用户标识或显示名称。"
                )

            if role not in VALID_ROLES:
                raise AuthenticationConfigurationError(
                    f"不支持的岗位角色：{role}"
                )

            raw_scope = item.get(
                "allowed_institution_ids",
                [],
            )

            if raw_scope == "*":
                scope = frozenset({"*"})
            elif isinstance(raw_scope, list):
                scope = frozenset(
                    str(value).strip()
                    for value in raw_scope
                    if str(value).strip()
                )
            else:
                raise AuthenticationConfigurationError(
                    "机构范围必须是数组或字符串*。"
                )

            principals[token] = SecurityPrincipal(
                subject_id=subject_id,
                display_name=display_name,
                role=role,
                allowed_institution_ids=scope,
                masking_profile=str(
                    item.get(
                        "masking_profile",
                        "none",
                    )
                ).strip(),
                authenticated=True,
            )

        if required and not principals:
            raise AuthenticationConfigurationError(
                "强制认证开启时必须配置访问令牌。"
            )

        return cls(
            authentication_required=required,
            principals_by_token=principals,
        )

    def authenticate(
        self,
        authorization: str | None,
        claimed_user_id: str,
    ) -> SecurityPrincipal:
        if authorization is None:
            if self.authentication_required:
                raise AuthenticationRequiredError(
                    "该接口需要访问凭证。"
                )

            return SecurityPrincipal(
                subject_id=claimed_user_id,
                display_name="兼容模式用户",
                role="legacy",
                allowed_institution_ids=None,
                masking_profile="none",
                authenticated=False,
            )

        scheme, separator, token = (
            authorization.strip().partition(" ")
        )

        if (
            separator != " "
            or scheme.lower() != "bearer"
            or not token.strip()
        ):
            raise InvalidAuthenticationError(
                "访问凭证格式无效。"
            )

        supplied_token = token.strip()

        for configured_token, principal in (
            self.principals_by_token.items()
        ):
            if (
                len(configured_token) == len(supplied_token)
                and hmac.compare_digest(
                    configured_token,
                    supplied_token,
                )
            ):
                return principal

        raise InvalidAuthenticationError(
            "访问凭证无效或已失效。"
        )


def _parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off", ""}:
        return False

    raise AuthenticationConfigurationError(
        "BANKINSIGHT_AUTH_REQUIRED必须是布尔值。"
    )
