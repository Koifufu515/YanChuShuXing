from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.adapters.audit.alerting_logger import AlertingAuditLogger
from app.adapters.audit.jsonl_alert_reader import JsonlSecurityAlertReader
from app.adapters.audit.jsonl_logger import JsonlAuditLogger
from app.adapters.audit.noop_logger import NoOpAuditLogger
from app.adapters.answering.deterministic_answer_composer import (
    DeterministicAnswerComposer,
)
from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.execution.deterministic_query_plan_executor import (
    DeterministicQueryPlanExecutor,
)
from app.adapters.formatting.template_formatter import TemplateResultFormatter
from app.adapters.generation.hybrid_generator import HybridSQLGenerator
from app.adapters.generation.llm_generator import LLMSQLGenerator
from app.adapters.generation.real_rule_generator import RealRuleSQLGenerator
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider
from app.adapters.planning.business_concept_fast_planner import (
    BusinessConceptFastPlanner,
    RoutingQueryPlanner,
)
from app.adapters.planning.llm_query_planner import LLMQueryPlanner
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.errors import ConfigurationError
from app.application.pipeline import QueryPipeline
from app.application.planned_pipeline import PlannedQueryPipeline
from app.core.data_source import resolve_database_path
from app.core.settings import Settings
from app.ports.audit_logger import AuditLogger
from app.ports.llm_provider import LLMProvider
from app.ports.query_plan_executor import QueryPlanExecutor
from app.ports.query_planner import QueryPlanner
from app.ports.query_service import QueryService
from app.ports.security_alert_reader import SecurityAlertReader
from app.ports.sql_generator import SQLGenerator


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def build_audit_logger(
    settings: Settings,
) -> AuditLogger:
    if settings.data_environment == "real":
        audit_dir = (
            PROJECT_ROOT
            / "data"
            / "private"
            / "audit"
        )

        return AlertingAuditLogger(
            delegate=JsonlAuditLogger(
                audit_dir
                / "query_audit.jsonl"
            ),
            alert_path=(
                audit_dir
                / "security_alerts.jsonl"
            ),
        )

    return NoOpAuditLogger()


def build_security_alert_reader(
) -> SecurityAlertReader:
    return JsonlSecurityAlertReader(
        PROJECT_ROOT
        / "data"
        / "private"
        / "audit"
        / "security_alerts.jsonl"
    )


def build_pipeline(
    database_path: Path | None = None,
    settings: Settings | None = None,
    llm_provider: LLMProvider | None = None,
    query_planner: QueryPlanner | None = None,
    query_plan_executor: QueryPlanExecutor | None = None,
    audit_logger: AuditLogger | None = None,
) -> QueryService:
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
    database_executor = SQLiteExecutor(resolved_database)
    resolved_audit_logger = (
        audit_logger
        if audit_logger is not None
        else build_audit_logger(
            resolved_settings
        )
    )

    if is_real:
        provider = llm_provider or DeepSeekLLMProvider(
            base_url=resolved_settings.llm_base_url,
            api_key=resolved_settings.llm_api_key,
            model=resolved_settings.llm_model,
        )
        planner = query_planner or _build_query_planner(
            provider,
            resolved_settings,
        )
        executor = query_plan_executor or DeterministicQueryPlanExecutor(
            database_executor
        )
        return PlannedQueryPipeline(
            query_planner=planner,
            query_plan_executor=executor,
            audit_logger=resolved_audit_logger,
            answer_composer=DeterministicAnswerComposer(),
            provider_name=resolved_settings.llm_provider,
        )

    return QueryPipeline(
        context_resolver=YAMLContextResolver(
            PROJECT_ROOT / "config" / "schema.yml",
            PROJECT_ROOT / "config" / "metrics.yml",
        ),
        sql_generator=_build_sql_generator(
            resolved_settings,
            llm_provider,
            prompt_profile="demo",
        ),
        safety_checker=SQLGlotSafetyChecker(),
        database_executor=database_executor,
        result_formatter=TemplateResultFormatter(),
        audit_logger=resolved_audit_logger,
    )


def _build_query_planner(
    provider: LLMProvider,
    settings: Settings,
) -> QueryPlanner:
    config_dir = PROJECT_ROOT / "config" / "query_planner"
    prompt_path = config_dir / "query_planner_prompt.md"
    schema_path = config_dir / "query_plan.schema.json"
    context_path = config_dir / "query_planner_context.json"
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("查询规划器配置文件无法读取。") from exc
    if not isinstance(schema, dict) or not isinstance(context, dict):
        raise ConfigurationError("查询规划器配置文件顶层必须是JSON对象。")
    fallback_planner = LLMQueryPlanner(
        provider=provider,
        prompt=prompt,
        schema=schema,
        context=context,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
    )
    return RoutingQueryPlanner(
        fast_planner=BusinessConceptFastPlanner(
            schema=schema,
            context=context,
        ),
        fallback_planner=fallback_planner,
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
def get_settings() -> Settings:
    return Settings.from_env(
        PROJECT_ROOT / ".env"
    )


@lru_cache(maxsize=1)
def get_audit_logger() -> AuditLogger:
    return build_audit_logger(
        get_settings()
    )


@lru_cache(maxsize=1)
def get_security_alert_reader(
) -> SecurityAlertReader:
    return build_security_alert_reader()


@lru_cache(maxsize=1)
def get_pipeline() -> QueryService:
    return build_pipeline(
        settings=get_settings(),
        audit_logger=get_audit_logger(),
    )


def configure_dependencies(app: Any) -> None:
    from app.api.query import (
        get_query_audit_logger,
        get_query_pipeline,
    )
    from app.api.security_alerts import (
        get_security_alert_reader as api_get_security_alert_reader,
    )

    app.dependency_overrides[
        get_query_pipeline
    ] = get_pipeline

    app.dependency_overrides[
        get_query_audit_logger
    ] = get_audit_logger

    app.dependency_overrides[
        api_get_security_alert_reader
    ] = get_security_alert_reader
