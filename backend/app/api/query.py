from __future__ import annotations

from functools import lru_cache
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Response,
)

from app.adapters.security.token_authenticator import (
    AuthenticationRequiredError,
    InvalidAuthenticationError,
    TokenAuthenticator,
)
from app.api.schemas import (
    QueryRequestDTO,
    QueryResponseDTO,
)
from app.application.models import (
    AuditEvent,
    ErrorDetail,
    QueryCommand,
    QueryOutcome,
)
from app.ports.audit_logger import AuditLogger
from app.ports.query_service import (
    QueryService,
)


router = APIRouter(
    prefix="/api/v1",
    tags=["query"],
)


def get_query_pipeline() -> QueryService:
    raise RuntimeError(
        "Query service dependency "
        "has not been configured."
    )


def get_query_audit_logger(
) -> AuditLogger | None:
    """
    API认证审计依赖。

    容器尚未接入时返回None，保持测试和兼容环境可用。
    """
    return None


@lru_cache(maxsize=1)
def get_token_authenticator(
) -> TokenAuthenticator:
    return (
        TokenAuthenticator
        .from_environment()
    )


@router.post(
    "/query",
    response_model=QueryResponseDTO,
)
@router.post(
    "/ask",
    response_model=QueryResponseDTO,
    include_in_schema=False,
)
def query(
    request: QueryRequestDTO,
    response: Response,
    authorization: str | None = Header(
        default=None,
    ),
    pipeline: QueryService = Depends(
        get_query_pipeline
    ),
    authenticator: TokenAuthenticator = Depends(
        get_token_authenticator
    ),
    audit_logger: AuditLogger | None = Depends(
        get_query_audit_logger
    ),
) -> QueryResponseDTO:
    request_id = (
        f"req_{uuid4().hex}"
    )

    try:
        principal = (
            authenticator.authenticate(
                authorization=authorization,
                claimed_user_id=(
                    request.user_id
                ),
            )
        )
    except AuthenticationRequiredError as exc:
        _record_authentication_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id=request.user_id,
            question=request.question,
            authenticated=False,
            security_action=(
                "authentication_required"
            ),
            error_code=(
                "AUTHENTICATION_REQUIRED"
            ),
        )

        return _authentication_failure(
            response=response,
            request_id=request_id,
            question=request.question,
            code=(
                "AUTHENTICATION_REQUIRED"
            ),
            message=str(exc),
        )
    except InvalidAuthenticationError as exc:
        _record_authentication_event(
            audit_logger,
            event_type="authentication_failed",
            request_id=request_id,
            user_id=request.user_id,
            question=request.question,
            authenticated=False,
            security_action=(
                "invalid_bearer_token"
            ),
            error_code=(
                "INVALID_AUTHENTICATION"
            ),
        )

        return _authentication_failure(
            response=response,
            request_id=request_id,
            question=request.question,
            code=(
                "INVALID_AUTHENTICATION"
            ),
            message=str(exc),
        )

    _record_authentication_event(
        audit_logger,
        event_type="authentication_succeeded",
        request_id=request_id,
        user_id=principal.subject_id,
        question=request.question,
        authenticated=principal.authenticated,
        security_action=(
            "token_authenticated"
            if principal.authenticated
            else "legacy_compatibility_access"
        ),
        actor_role=principal.role,
    )

    outcome = pipeline.run(
        QueryCommand(
            question=request.question,
            user_id=principal.subject_id,
            conversation_id=(
                request.conversation_id
            ),
            request_id=request_id,
            security_principal=principal,
        )
    )

    response.status_code = _status_for(
        (
            outcome.error.code
            if outcome.error
            else None
        )
    )

    return QueryResponseDTO.from_outcome(
        outcome
    )


def _record_authentication_event(
    audit_logger: AuditLogger | None,
    *,
    event_type: str,
    request_id: str,
    user_id: str,
    question: str,
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
                question=question,
                error_code=error_code,
                actor_role=actor_role,
                authenticated=authenticated,
                security_action=security_action,
            )
        )
    except Exception:
        return


def _authentication_failure(
    *,
    response: Response,
    request_id: str,
    question: str,
    code: str,
    message: str,
) -> QueryResponseDTO:
    response.status_code = 401
    response.headers[
        "WWW-Authenticate"
    ] = "Bearer"

    return QueryResponseDTO.from_outcome(
        QueryOutcome(
            request_id=request_id,
            question=question,
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=False,
            ),
        )
    )


def _status_for(
    error_code: str | None,
) -> int:
    if error_code is None:
        return 200

    return {
        "INVALID_QUESTION": 400,
        "UNSUPPORTED_QUESTION": 400,
        "CLARIFICATION_REQUIRED": 400,
        "UNSUPPORTED_METRIC": 400,
        "PENDING_PROJECT_DEFINITION": 422,
        "DATA_UNAVAILABLE": 422,
        "SQL_REJECTED": 403,
        "ACCESS_DENIED": 403,
        "LLM_PROVIDER_ERROR": 502,
        "DATABASE_UNAVAILABLE": 503,
        "LLM_UNAVAILABLE": 503,
        "QUERY_TIMEOUT": 504,
        "LLM_TIMEOUT": 504,
    }.get(
        error_code,
        500,
    )
