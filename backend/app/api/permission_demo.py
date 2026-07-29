from __future__ import annotations

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
from app.application.errors import ApplicationError
from app.application.institution_scope import (
    InstitutionAccessDeniedError,
    require_institution_access,
)
from app.application.models import (
    AuditEvent,
    JsonScalar,
)
from app.application.result_security import (
    secure_result,
)
from app.application.row_scope import (
    RowScopeEnforcementError,
    apply_relationship_manager_scope,
)
from app.ports.audit_logger import AuditLogger
from app.ports.database_executor import (
    DatabaseExecutor,
)


router = APIRouter(
    prefix="/api/v1/security",
    tags=["security"],
)

_ALLOWED_ROLES = {
    "admin",
    "province_analyst",
    "institution_analyst",
    "relationship_manager",
}

_DEMO_QUERY = """
SELECT
    customer_id,
    institution_id,
    rm_id,
    customer_name,
    phone,
    id_card,
    account_number,
    aum_scaled,
    risk_level,
    internal_remark,
    data_classification
FROM demo_customer_portfolio
WHERE institution_id = :institution_id
ORDER BY customer_id
"""


class PermissionDemoResponse(BaseModel):
    request_id: str
    subject_id: str
    role: str
    institution_id: str
    data_classification: str
    source_row_count: int
    row_count: int
    row_scope_applied: bool
    removed_row_count: int
    columns: list[str]
    rows: list[list[JsonScalar]]
    masked_columns: list[str]
    removed_columns: list[str]


def get_permission_demo_executor(
) -> DatabaseExecutor:
    raise RuntimeError(
        "Permission demo database dependency "
        "has not been configured."
    )


@router.get(
    "/demo-portfolio",
    response_model=PermissionDemoResponse,
)
def read_permission_demo_portfolio(
    institution_id: str = Query(
        pattern=r"^ORG\d{3}$",
    ),
    authorization: str | None = Header(
        default=None,
    ),
    authenticator: TokenAuthenticator = Depends(
        get_token_authenticator
    ),
    executor: DatabaseExecutor = Depends(
        get_permission_demo_executor
    ),
    audit_logger: AuditLogger | None = Depends(
        get_query_audit_logger
    ),
):
    request_id = f"req_{uuid4().hex}"

    if authorization is None:
        _record_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action="authentication_required",
            error_code="AUTHENTICATION_REQUIRED",
            institution_id=institution_id,
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
                "permission_demo_reader"
            ),
        )
    except AuthenticationRequiredError as exc:
        return _error_response(
            status_code=401,
            request_id=request_id,
            code="AUTHENTICATION_REQUIRED",
            message=str(exc),
            authenticate=True,
        )
    except InvalidAuthenticationError as exc:
        _record_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id="anonymous",
            authenticated=False,
            security_action="invalid_bearer_token",
            error_code="INVALID_AUTHENTICATION",
            institution_id=institution_id,
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
        _record_event(
            audit_logger,
            event_type="access_denied",
            request_id=request_id,
            user_id=principal.subject_id,
            actor_role=principal.role,
            authenticated=principal.authenticated,
            security_action=(
                "permission_demo_role_denied"
            ),
            error_code=(
                "PORTFOLIO_ACCESS_DENIED"
            ),
            institution_id=institution_id,
        )
        return _error_response(
            status_code=403,
            request_id=request_id,
            code="PORTFOLIO_ACCESS_DENIED",
            message=(
                "当前岗位无权查看客户组合数据。"
            ),
        )

    try:
        require_institution_access(
            {
                "institution_id": institution_id,
            },
            principal,
        )
    except InstitutionAccessDeniedError as exc:
        _record_event(
            audit_logger,
            event_type="access_denied",
            request_id=request_id,
            user_id=principal.subject_id,
            actor_role=principal.role,
            authenticated=True,
            security_action=(
                "institution_scope_denied"
            ),
            error_code="ACCESS_DENIED",
            institution_id=institution_id,
        )
        return _error_response(
            status_code=403,
            request_id=request_id,
            code="ACCESS_DENIED",
            message=str(exc),
        )

    try:
        raw_result = executor.execute_query(
            _DEMO_QUERY,
            {
                "institution_id": institution_id,
            },
            max_rows=200,
        )

        row_scoped = (
            apply_relationship_manager_scope(
                columns=raw_result.columns,
                rows=raw_result.rows,
                principal=principal,
            )
        )

        secured = secure_result(
            columns=row_scoped.columns,
            rows=row_scoped.rows,
            principal=principal,
        )
    except RowScopeEnforcementError as exc:
        _record_event(
            audit_logger,
            event_type="access_denied",
            request_id=request_id,
            user_id=principal.subject_id,
            actor_role=principal.role,
            authenticated=True,
            security_action=(
                "row_scope_enforcement_failed"
            ),
            error_code=exc.code,
            institution_id=institution_id,
        )
        return _error_response(
            status_code=403,
            request_id=request_id,
            code=exc.code,
            message=str(exc),
        )
    except ApplicationError:
        return _error_response(
            status_code=503,
            request_id=request_id,
            code="PERMISSION_DEMO_UNAVAILABLE",
            message="权限演示数据暂不可用。",
        )

    _record_event(
        audit_logger,
        event_type="permission_demo_portfolio_read",
        request_id=request_id,
        user_id=principal.subject_id,
        actor_role=principal.role,
        authenticated=True,
        security_action=(
            "relationship_manager_row_scope_applied"
            if row_scoped.applied
            else "permission_demo_portfolio_read"
        ),
        masking_profile=principal.masking_profile,
        affected_column_count=(
            len(secured.masked_columns)
            + len(secured.removed_columns)
        ),
        institution_id=institution_id,
    )

    return PermissionDemoResponse(
        request_id=request_id,
        subject_id=principal.subject_id,
        role=principal.role,
        institution_id=institution_id,
        data_classification=(
            "synthetic_permission_demo"
        ),
        source_row_count=raw_result.row_count,
        row_count=len(secured.rows),
        row_scope_applied=row_scoped.applied,
        removed_row_count=(
            row_scoped.removed_row_count
        ),
        columns=secured.columns,
        rows=secured.rows,
        masked_columns=secured.masked_columns,
        removed_columns=secured.removed_columns,
    )


def _record_event(
    audit_logger: AuditLogger | None,
    *,
    event_type: str,
    request_id: str,
    user_id: str,
    authenticated: bool,
    security_action: str,
    institution_id: str,
    error_code: str | None = None,
    actor_role: str | None = None,
    masking_profile: str | None = None,
    affected_column_count: int | None = None,
) -> None:
    if audit_logger is None:
        return

    try:
        audit_logger.record(
            AuditEvent(
                event_type=event_type,
                request_id=request_id,
                user_id=user_id,
                question=(
                    "读取合成权限演示客户组合："
                    f"{institution_id}"
                ),
                error_code=error_code,
                actor_role=actor_role,
                authenticated=authenticated,
                security_action=security_action,
                masking_profile=masking_profile,
                affected_column_count=(
                    affected_column_count
                ),
                referenced_institution_count=1,
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
