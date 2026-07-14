from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.models import QueryMetadata


class ApplicationError(Exception):
    code = "APPLICATION_ERROR"
    retryable = False

    def __init__(
        self, message: str, metadata: QueryMetadata | None = None
    ) -> None:
        super().__init__(message)
        self.public_message = message
        self.metadata = metadata

    def with_metadata(self, metadata: QueryMetadata) -> ApplicationError:
        self.metadata = metadata
        return self


class UnsupportedQuestionError(ApplicationError):
    code = "UNSUPPORTED_QUESTION"


class RuleNotMatchedError(UnsupportedQuestionError):
    """Internal routing signal; externally remains an unsupported question."""


class ProviderUnavailableError(ApplicationError):
    code = "LLM_UNAVAILABLE"
    retryable = True


class ProviderTimeoutError(ApplicationError):
    code = "LLM_TIMEOUT"
    retryable = True


class InvalidProviderOutputError(ApplicationError):
    code = "LLM_PROVIDER_ERROR"


class InvalidSemanticOutputError(InvalidProviderOutputError):
    code = "INVALID_SEMANTIC_OUTPUT"


class InvalidSQLOutputError(InvalidProviderOutputError):
    code = "INVALID_SQL_OUTPUT"


class ClarificationRequiredError(UnsupportedQuestionError):
    code = "CLARIFICATION_REQUIRED"


class UnsupportedMetricError(InvalidSemanticOutputError):
    code = "UNSUPPORTED_METRIC"


class DatabaseUnavailableError(ApplicationError):
    code = "DATABASE_UNAVAILABLE"
    retryable = True


class QueryExecutionError(ApplicationError):
    code = "QUERY_EXECUTION_ERROR"


class QueryTimeoutError(ApplicationError):
    code = "QUERY_TIMEOUT"
    retryable = True


class ConfigurationError(ApplicationError):
    code = "CONFIGURATION_ERROR"
