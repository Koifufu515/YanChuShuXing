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
from app.application.models import LLMRequest, LLMResponse


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
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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

        content, response_model = self._parse_response(raw)
        return LLMResponse(
            text=content,
            model=response_model or self.model,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def _validate_configuration(self) -> None:
        if not self._api_key or not self.model or not self.base_url:
            raise ConfigurationError("LLM 模式缺少必要的 DeepSeek 配置。")
        if not self.base_url.startswith("https://"):
            raise ConfigurationError("DeepSeek Base URL 必须使用 HTTPS。")

    @staticmethod
    def _parse_response(raw: bytes) -> tuple[str, str | None]:
        try:
            payload = json.loads(raw.decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            model = payload.get("model")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise InvalidProviderOutputError("DeepSeek 返回格式不符合预期。") from exc
        if not isinstance(content, str) or not content.strip():
            raise InvalidProviderOutputError("DeepSeek 返回了空内容。")
        return content.strip(), model if isinstance(model, str) else None
