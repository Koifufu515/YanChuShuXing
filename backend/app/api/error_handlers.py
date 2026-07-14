from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        question = ""
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                question = str(payload.get("question", ""))
        except Exception:
            pass
        return _error_response(
            status_code=422,
            question=question,
            code="REQUEST_VALIDATION_ERROR",
            message="请求字段缺失或格式不正确。",
            retryable=False,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return _error_response(
            status_code=500,
            question="",
            code="INTERNAL_ERROR",
            message="系统内部错误，请稍后重试。",
            retryable=False,
        )


def _error_response(
    status_code: int,
    question: str,
    code: str,
    message: str,
    retryable: bool,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "request_id": f"req_{uuid4().hex}",
            "question": question,
            "sql": None,
            "columns": [],
            "rows": [],
            "summary": None,
            "warnings": [],
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            },
            "metadata": None,
        },
    )
