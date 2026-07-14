from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from app.api.schemas import QueryRequestDTO, QueryResponseDTO
from app.application.models import QueryCommand
from app.application.pipeline import QueryPipeline


router = APIRouter(prefix="/api/v1", tags=["query"])


def get_query_pipeline() -> QueryPipeline:
    raise RuntimeError("QueryPipeline dependency has not been configured.")


@router.post("/query", response_model=QueryResponseDTO)
@router.post("/ask", response_model=QueryResponseDTO, include_in_schema=False)
def query(
    request: QueryRequestDTO,
    response: Response,
    pipeline: QueryPipeline = Depends(get_query_pipeline),
) -> QueryResponseDTO:
    outcome = pipeline.run(
        QueryCommand(
            question=request.question,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            request_id=f"req_{uuid4().hex}",
        )
    )
    response.status_code = _status_for(outcome.error.code if outcome.error else None)
    return QueryResponseDTO.from_outcome(outcome)


def _status_for(error_code: str | None) -> int:
    if error_code is None:
        return 200
    return {
        "INVALID_QUESTION": 400,
        "UNSUPPORTED_QUESTION": 400,
        "CLARIFICATION_REQUIRED": 400,
        "UNSUPPORTED_METRIC": 400,
        "SQL_REJECTED": 403,
        "ACCESS_DENIED": 403,
        "LLM_PROVIDER_ERROR": 502,
        "DATABASE_UNAVAILABLE": 503,
        "LLM_UNAVAILABLE": 503,
        "QUERY_TIMEOUT": 504,
        "LLM_TIMEOUT": 504,
    }.get(error_code, 500)
