from __future__ import annotations

from dataclasses import replace

from app.application.errors import (
    ApplicationError,
    ClarificationRequiredError,
    ConfigurationError,
    InvalidProviderOutputError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RuleNotMatchedError,
    UnsupportedMetricError,
    UnsupportedQuestionError,
)
from app.application.models import GeneratedSQL, QueryContext
from app.application.models import QueryMetadata
from app.ports.sql_generator import SQLGenerator


class HybridSQLGenerator:
    name = "hybrid"

    def __init__(
        self,
        llm_generator: SQLGenerator,
        rule_generator: SQLGenerator,
        provider_name: str | None = None,
        model: str | None = None,
    ) -> None:
        self.llm_generator = llm_generator
        self.rule_generator = rule_generator
        self.provider_name = provider_name
        self.model = model

    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        try:
            generated = self.rule_generator.generate(question, context)
        except RuleNotMatchedError:
            return self._generate_with_llm(question, context)
        return _with_route(generated, "Rule", rule_matched=True)

    def _generate_with_llm(
        self, question: str, context: QueryContext
    ) -> GeneratedSQL:
        try:
            generated = self.llm_generator.generate(question, context)
        except ApplicationError as error:
            metadata = QueryMetadata(
                configured_mode="hybrid",
                executed_generator="llm",
                rule_matched=False,
                route="LLM",
                failure_reason=_failure_reason(error),
                provider=self.provider_name,
                model=self.model,
            )
            raise error.with_metadata(metadata)
        return _with_route(generated, "LLM", rule_matched=False)


def _with_route(
    generated: GeneratedSQL, route: str, rule_matched: bool
) -> GeneratedSQL:
    metadata = generated.metadata or QueryMetadata(
        configured_mode="hybrid",
        executed_generator=route.lower(),
    )
    return GeneratedSQL(
        sql=generated.sql,
        parameters=generated.parameters,
        generator_name=f"hybrid:{generated.generator_name}",
        warnings=generated.warnings,
        metadata=replace(
            metadata,
            configured_mode="hybrid",
            executed_generator=route.lower(),
            rule_matched=rule_matched,
            route=route,
            failure_reason=None,
        ),
    )


def _failure_reason(error: ApplicationError) -> str:
    if isinstance(error, ClarificationRequiredError):
        return "missing_parameter"
    if isinstance(error, UnsupportedMetricError):
        return "unsupported_metric"
    if isinstance(error, ProviderTimeoutError):
        return "llm_timeout"
    if isinstance(error, ProviderUnavailableError):
        return "llm_unavailable"
    if isinstance(error, ConfigurationError):
        return "configuration_error"
    if isinstance(error, InvalidProviderOutputError):
        return "invalid_llm_output"
    if isinstance(error, UnsupportedQuestionError):
        return "unsupported_question"
    return "generation_failed"
