from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app.application.errors import ConfigurationError


VALID_GENERATOR_MODES = {"rule", "llm", "hybrid"}


@dataclass(frozen=True)
class Settings:
    generator_mode: str = "rule"
    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = 20.0
    llm_temperature: float = 0.0

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        if env_file:
            load_dotenv(env_file, override=False)
        mode = os.getenv("BANKINSIGHT_GENERATOR_MODE", "rule").strip().lower()
        provider = os.getenv("BANKINSIGHT_LLM_PROVIDER", "deepseek").strip().lower()
        if mode not in VALID_GENERATOR_MODES:
            raise ConfigurationError("BANKINSIGHT_GENERATOR_MODE 必须是 rule、llm 或 hybrid。")
        if provider != "deepseek":
            raise ConfigurationError("当前仅支持 deepseek LLM Provider。")
        try:
            timeout = float(os.getenv("BANKINSIGHT_LLM_TIMEOUT_SECONDS", "20"))
            temperature = float(os.getenv("BANKINSIGHT_LLM_TEMPERATURE", "0"))
        except ValueError as exc:
            raise ConfigurationError("LLM 超时或温度配置格式不正确。") from exc
        if timeout <= 0 or not 0 <= temperature <= 2:
            raise ConfigurationError("LLM 超时或温度配置超出允许范围。")
        return cls(
            generator_mode=mode,
            llm_provider=provider,
            llm_base_url=os.getenv("BANKINSIGHT_LLM_BASE_URL", "https://api.deepseek.com").strip(),
            llm_api_key=os.getenv("BANKINSIGHT_LLM_API_KEY", "").strip(),
            llm_model=os.getenv("BANKINSIGHT_LLM_MODEL", "deepseek-v4-flash").strip(),
            llm_timeout_seconds=timeout,
            llm_temperature=temperature,
        )
