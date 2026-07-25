from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.adapters.audit.noop_logger import NoOpAuditLogger
from app.adapters.context.real_database_resolver import RealDatabaseContextResolver
from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.formatting.real_result_formatter import RealResultFormatter
from app.adapters.formatting.template_formatter import TemplateResultFormatter
from app.adapters.generation.hybrid_generator import HybridSQLGenerator
from app.adapters.generation.llm_generator import LLMSQLGenerator
from app.adapters.generation.real_rule_generator import RealRuleSQLGenerator
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.pipeline import QueryPipeline
from app.core.data_source import resolve_database_path
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
    resolved_database = (
        Path(database_path).resolve()
        if database_path
        else resolve_database_path(
            PROJECT_ROOT,
            resolved_settings.data_environment,
            resolved_settings.database_path_override,
        )
    )
    is_real = resolved_settings.data_environment == "real"
    return QueryPipeline(
        context_resolver=(
            RealDatabaseContextResolver(resolved_database)
            if is_real
            else YAMLContextResolver(
                PROJECT_ROOT / "config" / "schema.yml",
                PROJECT_ROOT / "config" / "metrics.yml",
            )
        ),
        sql_generator=_build_sql_generator(
            resolved_settings,
            llm_provider,
            prompt_profile="real" if is_real else "demo",
        ),
        safety_checker=SQLGlotSafetyChecker(),
        database_executor=SQLiteExecutor(resolved_database),
        result_formatter=(
            RealResultFormatter() if is_real else TemplateResultFormatter()
        ),
        audit_logger=NoOpAuditLogger(),
    )


def _build_sql_generator(
    settings: Settings,
    llm_provider: LLMProvider | None = None,
    prompt_profile: str = "demo",
) -> SQLGenerator:
    rule_generator: SQLGenerator = (
        RealRuleSQLGenerator()
        if prompt_profile == "real"
        else RuleSQLGenerator(configured_mode=settings.generator_mode)
    )
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
        prompt_profile=prompt_profile,
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
