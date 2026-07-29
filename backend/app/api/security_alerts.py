from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
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
from app.application.security_alerts import (
    SecurityAlertRecord,
)
from app.ports.audit_logger import AuditLogger
from app.ports.security_alert_reader import (
    SecurityAlertReader,
)


router = APIRouter(
    prefix="/api/v1/security",
    tags=["security"],
)

_ALLOWED_ROLES = {
    "admin",
    "auditor",
}


class SecurityAlertDTO(BaseModel):
    occurred_at: datetime
    alert_type: str
    severity: str
    event_count: int
    window_seconds: int
    security_action: str
    trigger_event_type: str
    trigger_error_code: str | None
    request_id: str
    actor_fingerprint: str

    @classmethod
    def from_model(
        cls,
        record: SecurityAlertRecord,
    ) -> "SecurityAlertDTO":
        return cls(
            occurred_at=record.occurred_at,
            alert_type=record.alert_type,
            severity=record.severity,
            event_count=record.event_count,
            window_seconds=record.window_seconds,
            security_action=record.security_action,
            trigger_event_type=(
                record.trigger_event_type
            ),
            trigger_error_code=(
                record.trigger_error_code
            ),
            request_id=record.request_id,
            actor_fingerprint=(
                record.actor_sha256[:12]
            ),
        )


class SecurityAlertListDTO(BaseModel):
    request_id: str
    count: int
    alerts: list[SecurityAlertDTO]


def get_security_alert_reader(
) -> SecurityAlertReader:
    raise RuntimeError(
        "Security alert reader dependency "
        "has not been configured."
    )


@router.get(
    "/alerts",
    response_model=SecurityAlertListDTO,
)
def list_security_alerts(
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
    authorization: str | None = Header(
        default=None,
    ),
    authenticator: TokenAuthenticator = Depends(
        get_token_authenticator
    ),
    reader: SecurityAlertReader = Depends(
        get_security_alert_reader
    ),
    audit_logger: AuditLogger | None = Depends(
        get_query_audit_logger
    ),
):
    request_id = f"req_{uuid4().hex}"

    if authorization is None:
        _record_access(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action=(
                "authentication_required"
            ),
            error_code=(
                "AUTHENTICATION_REQUIRED"
            ),
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
            claimed_user_id=(
                "security_alert_reader"
            ),
        )
    except AuthenticationRequiredError as exc:
        _record_access(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action=(
                "authentication_required"
            ),
            error_code=(
                "AUTHENTICATION_REQUIRED"
            ),
        )
        return _error_response(
            status_code=401,
            request_id=request_id,
            code="AUTHENTICATION_REQUIRED",
            message=str(exc),
            authenticate=True,
        )
    except InvalidAuthenticationError as exc:
        _record_access(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action=(
                "invalid_bearer_token"
            ),
            error_code=(
                "INVALID_AUTHENTICATION"
            ),
        )
        return _error_response(
            status_code=401,
            request_id=request_id,
            code="INVALID_AUTHENTICATION",
            message=str(exc),
            authenticate=True,
        )

    if (
        not principal.authenticated
        or principal.role not in _ALLOWED_ROLES
    ):
        _record_access(
            audit_logger,
            event_type="access_denied",
            request_id=request_id,
            user_id=principal.subject_id,
            actor_role=principal.role,
            authenticated=(
                principal.authenticated
            ),
            security_action=(
                "security_alert_access_denied"
            ),
            error_code=(
                "ALERT_ACCESS_DENIED"
            ),
        )
        return _error_response(
            status_code=403,
            request_id=request_id,
            code="ALERT_ACCESS_DENIED",
            message=(
                "当前账号无权读取安全告警。"
            ),
        )

    records = reader.read_recent(
        limit=limit
    )

    _record_access(
        audit_logger,
        event_type="security_alerts_read",
        request_id=request_id,
        user_id=principal.subject_id,
        actor_role=principal.role,
        authenticated=True,
        security_action="security_alerts_read",
    )

    alerts = [
        SecurityAlertDTO.from_model(record)
        for record in records
    ]

    return SecurityAlertListDTO(
        request_id=request_id,
        count=len(alerts),
        alerts=alerts,
    )


def _record_access(
    audit_logger: AuditLogger | None,
    *,
    event_type: str,
    request_id: str,
    user_id: str,
    authenticated: bool,
    security_action: str,
    error_code: str | None = None,
    actor_role: str | None = None,
) -> None:
    if audit_logger is None:
        return

    try:
        audit_logger.record(
            AuditEvent(
                event_type=event_type,
                request_id=request_id,
                user_id=user_id,
                question="读取安全告警",
                error_code=error_code,
                actor_role=actor_role,
                authenticated=authenticated,
                security_action=security_action,
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
