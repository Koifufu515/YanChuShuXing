from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.adapters.audit.noop_logger import NoOpAuditLogger
from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.formatting.template_formatter import TemplateResultFormatter
from app.adapters.generation.hybrid_generator import HybridSQLGenerator
from app.adapters.generation.llm_generator import LLMSQLGenerator
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.pipeline import QueryPipeline
from app.core.settings import Settings
from app.ports.llm_provider import LLMProvider
from app.ports.sql_generator import SQLGenerator


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def build_pipeline(
    database_path: Path | None = None,
    settings: Settings | None = None,
    llm_provider: LLMProvider | None = None,
) -> QueryPipeline:
    resolved_settings = settings or Settings.from_env(PROJECT_ROOT / ".env")
    resolved_database = database_path or Path(
        os.getenv(
            "BANKINSIGHT_DB_PATH",
            PROJECT_ROOT / "data" / "processed" / "bankinsight.db",
        )
    )
    return QueryPipeline(
        context_resolver=YAMLContextResolver(
            PROJECT_ROOT / "config" / "schema.yml",
            PROJECT_ROOT / "config" / "metrics.yml",
        ),
        sql_generator=_build_sql_generator(resolved_settings, llm_provider),
        safety_checker=SQLGlotSafetyChecker(),
        database_executor=SQLiteExecutor(resolved_database),
        result_formatter=TemplateResultFormatter(),
        audit_logger=NoOpAuditLogger(),
    )


def _build_sql_generator(
    settings: Settings, llm_provider: LLMProvider | None = None
) -> SQLGenerator:
    rule_generator = RuleSQLGenerator(configured_mode=settings.generator_mode)
    if settings.generator_mode == "rule":
        return rule_generator

    provider = llm_provider or DeepSeekLLMProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    llm_generator = LLMSQLGenerator(
        provider=provider,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        configured_mode=settings.generator_mode,
        provider_name=settings.llm_provider,
    )
    if settings.generator_mode == "llm":
        return llm_generator
    return HybridSQLGenerator(
        llm_generator,
        rule_generator,
        provider_name=settings.llm_provider,
        model=settings.llm_model,
    )


@lru_cache(maxsize=1)
def get_pipeline() -> QueryPipeline:
    return build_pipeline()


def configure_dependencies(app: Any) -> None:
    from app.api.query import get_query_pipeline

    app.dependency_overrides[get_query_pipeline] = get_pipeline
