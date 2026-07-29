from __future__ import annotations

from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Header,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.adapters.security.token_authenticator import (
    AuthenticationRequiredError,
    InvalidAuthenticationError,
    TokenAuthenticator,
)
from app.api.query import (
    get_query_audit_logger,
    get_token_authenticator,
)
from app.application.models import AuditEvent
from app.application.security_models import (
    SecurityPrincipal,
)
from app.ports.audit_logger import AuditLogger


router = APIRouter(
    prefix="/api/v1/session",
    tags=["session"],
)


ROLE_LABELS = {
    "admin": "系统管理员",
    "province_analyst": "省级分析岗",
    "institution_analyst": "机构分析岗",
    "relationship_manager": "客户经理",
    "auditor": "安全审计岗",
}

PERMISSION_DEMO_ROLES = {
    "admin",
    "province_analyst",
    "institution_analyst",
    "relationship_manager",
}

SECURITY_ALERT_ROLES = {
    "admin",
    "auditor",
}


class AccessScopeDTO(BaseModel):
    enforced: bool
    all_access: bool
    ids: list[str]


class SessionCapabilitiesDTO(BaseModel):
    can_query: bool
    can_view_permission_demo: bool
    can_view_security_alerts: bool
    row_scope_active: bool


class SessionProfileDTO(BaseModel):
    request_id: str
    subject_id: str
    display_name: str
    role: str
    role_label: str
    authenticated: bool
    masking_profile: str
    institution_scope: AccessScopeDTO
    relationship_manager_scope: AccessScopeDTO
    capabilities: SessionCapabilitiesDTO


@router.get(
    "/me",
    response_model=SessionProfileDTO,
)
def read_current_session(
    authorization: str | None = Header(
        default=None,
    ),
    authenticator: TokenAuthenticator = Depends(
        get_token_authenticator
    ),
    audit_logger: AuditLogger | None = Depends(
        get_query_audit_logger
    ),
):
    request_id = f"req_{uuid4().hex}"

    if authorization is None:
        _record_session_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action="authentication_required",
            error_code="AUTHENTICATION_REQUIRED",
        )
        return _error_response(
            status_code=401,
            request_id=request_id,
            code="AUTHENTICATION_REQUIRED",
            message="该接口需要访问凭证。",
            authenticate=True,
        )

    try:
        principal = authenticator.authenticate(
            authorization=authorization,
            claimed_user_id="session_reader",
        )
    except AuthenticationRequiredError as exc:
        _record_session_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action="authentication_required",
            error_code="AUTHENTICATION_REQUIRED",
        )
        return _error_response(
            status_code=401,
            request_id=request_id,
            code="AUTHENTICATION_REQUIRED",
            message=str(exc),
            authenticate=True,
        )
    except InvalidAuthenticationError as exc:
        _record_session_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action="invalid_bearer_token",
            error_code="INVALID_AUTHENTICATION",
        )
        return _error_response(
            status_code=401,
            request_id=request_id,
            code="INVALID_AUTHENTICATION",
            message=str(exc),
            authenticate=True,
        )

    institution_scope = _serialize_scope(
        principal.allowed_institution_ids,
        none_means_all=True,
    )
    rm_scope = _serialize_scope(
        principal.allowed_rm_ids,
        none_means_all=False,
    )

    row_scope_active = (
        principal.allowed_rm_ids is not None
        and "*" not in principal.allowed_rm_ids
    )

    _record_session_event(
        audit_logger,
        event_type="session_profile_read",
        request_id=request_id,
        user_id=principal.subject_id,
        authenticated=principal.authenticated,
        security_action="session_profile_read",
        actor_role=principal.role,
        masking_profile=principal.masking_profile,
    )

    return SessionProfileDTO(
        request_id=request_id,
        subject_id=principal.subject_id,
        display_name=principal.display_name,
        role=principal.role,
        role_label=ROLE_LABELS.get(
            principal.role,
            principal.role,
        ),
        authenticated=principal.authenticated,
        masking_profile=principal.masking_profile,
        institution_scope=institution_scope,
        relationship_manager_scope=rm_scope,
        capabilities=SessionCapabilitiesDTO(
            can_query=True,
            can_view_permission_demo=(
                principal.role
                in PERMISSION_DEMO_ROLES
            ),
            can_view_security_alerts=(
                principal.role
                in SECURITY_ALERT_ROLES
            ),
            row_scope_active=row_scope_active,
        ),
    )


def _serialize_scope(
    scope: frozenset[str] | None,
    *,
    none_means_all: bool,
) -> AccessScopeDTO:
    if scope is None:
        return AccessScopeDTO(
            enforced=False,
            all_access=none_means_all,
            ids=[],
        )

    if "*" in scope:
        return AccessScopeDTO(
            enforced=True,
            all_access=True,
            ids=[],
        )

    return AccessScopeDTO(
        enforced=True,
        all_access=False,
        ids=sorted(scope),
    )


def _record_session_event(
    audit_logger: AuditLogger | None,
    *,
    event_type: str,
    request_id: str,
    user_id: str,
    authenticated: bool,
    security_action: str,
    error_code: str | None = None,
    actor_role: str | None = None,
    masking_profile: str | None = None,
) -> None:
    if audit_logger is None:
        return

    try:
        audit_logger.record(
            AuditEvent(
                event_type=event_type,
                request_id=request_id,
                user_id=user_id,
                question="读取当前会话身份",
                error_code=error_code,
                actor_role=actor_role,
                authenticated=authenticated,
                security_action=security_action,
                masking_profile=masking_profile,
            )
        )
    except Exception:
        return


def _error_response(
    *,
    status_code: int,
    request_id: str,
    code: str,
    message: str,
    authenticate: bool = False,
) -> JSONResponse:
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if authenticate
        else None
    )

    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "request_id": request_id,
            "error": {
                "code": code,
                "message": message,
                "retryable": False,
            },
        },
    )
