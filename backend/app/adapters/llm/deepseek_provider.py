from __future__ import annotations

import json
import ssl
import time
import urllib.request
from urllib.error import HTTPError, URLError

import certifi

from app.application.errors import (
    ConfigurationError,
    InvalidProviderOutputError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.application.models import (
    LLMCallTelemetry,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)


class DeepSeekLLMProvider:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        self._validate_configuration()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        if request.response_format:
            payload["response_format"] = {"type": request.response_format}
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                http_request,
                timeout=request.timeout_seconds,
                context=ssl.create_default_context(cafile=certifi.where()),
            ) as response:
                raw = response.read()
        except (TimeoutError, OSError) as exc:
            if isinstance(exc, HTTPError):
                raise ProviderUnavailableError("DeepSeek 服务暂时不可用。") from exc
            if isinstance(exc, URLError) and not isinstance(exc.reason, TimeoutError):
                raise ProviderUnavailableError("DeepSeek 服务暂时不可用。") from exc
            raise ProviderTimeoutError("DeepSeek 请求超时，请稍后重试。") from exc

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        content, response_model, usage = self._parse_response(raw)
        return LLMResponse(
            text=content,
            model=response_model or self.model,
            latency_ms=latency_ms,
            telemetry=LLMCallTelemetry(
                latency_ms=latency_ms,
                request_body_bytes=len(request_body),
                response_body_bytes=len(raw),
                usage=usage,
            ),
        )

    def _validate_configuration(self) -> None:
        if not self._api_key or not self.model or not self.base_url:
            raise ConfigurationError("LLM 模式缺少必要的 DeepSeek 配置。")
        if not self.base_url.startswith("https://"):
            raise ConfigurationError("DeepSeek Base URL 必须使用 HTTPS。")

    @staticmethod
    def _parse_response(raw: bytes) -> tuple[str, str | None, LLMUsage]:
        try:
            payload = json.loads(raw.decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            model = payload.get("model")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise InvalidProviderOutputError("DeepSeek 返回格式不符合预期。") from exc
        if not isinstance(content, str) or not content.strip():
            raise InvalidProviderOutputError("DeepSeek 返回了空内容。")
        return (
            content.strip(),
            model if isinstance(model, str) else None,
            DeepSeekLLMProvider._parse_usage(payload.get("usage")),
        )

    @staticmethod
    def _parse_usage(raw_usage: object) -> LLMUsage:
        if not isinstance(raw_usage, dict):
            return LLMUsage()
        completion_details = raw_usage.get("completion_tokens_details")
        if not isinstance(completion_details, dict):
            completion_details = {}

        def safe_int(value: object) -> int:
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
            return 0

        return LLMUsage(
            prompt_tokens=safe_int(raw_usage.get("prompt_tokens")),
            prompt_cache_hit_tokens=safe_int(
                raw_usage.get("prompt_cache_hit_tokens")
            ),
            prompt_cache_miss_tokens=safe_int(
                raw_usage.get("prompt_cache_miss_tokens")
            ),
            completion_tokens=safe_int(raw_usage.get("completion_tokens")),
            reasoning_tokens=safe_int(completion_details.get("reasoning_tokens")),
            total_tokens=safe_int(raw_usage.get("total_tokens")),
        )
