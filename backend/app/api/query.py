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
    ErrorDetail,
    QueryCommand,
    QueryOutcome,
)
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
        return _authentication_failure(
            response=response,
            request_id=request_id,
            question=request.question,
            code=(
                "INVALID_AUTHENTICATION"
            ),
            message=str(exc),
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
