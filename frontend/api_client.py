from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError


class APIConnectionError(RuntimeError):
    """Raised when the product demo cannot reach a usable backend API."""


@dataclass(frozen=True)
class APIResult:
    payload: dict
    elapsed_ms: int


class BankInsightClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def query(
        self,
        question: str,
        user_id: str = "demo_user",
        conversation_id: str = "product_demo",
    ) -> APIResult:
        request_body = json.dumps(
            {
                "question": question,
                "user_id": user_id,
                "conversation_id": conversation_id,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/v1/query",
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = self._decode(response.read())
        except HTTPError as error:
            payload = self._decode(error.read())
        except (URLError, TimeoutError, OSError) as error:
            raise APIConnectionError(
                "无法连接 BankInsight API，请确认后端服务已经启动。"
            ) from error
        return APIResult(
            payload=payload,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _decode(body: bytes) -> dict:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise APIConnectionError("BankInsight API 返回了无法识别的响应。") from error
        if not isinstance(payload, dict):
            raise APIConnectionError("BankInsight API 返回格式不正确。")
        return payload
