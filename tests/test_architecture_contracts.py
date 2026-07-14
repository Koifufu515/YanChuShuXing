import inspect
import unittest


class ArchitectureContractTest(unittest.TestCase):
    def test_application_models_and_ports_are_framework_independent(self) -> None:
        from app.application import models
        from app.ports.audit_logger import AuditLogger
        from app.ports.context_resolver import ContextResolver
        from app.ports.database_executor import DatabaseExecutor
        from app.ports.llm_provider import LLMProvider
        from app.ports.result_formatter import ResultFormatter
        from app.ports.sql_generator import SQLGenerator
        from app.ports.sql_safety import SQLSafetyChecker

        source = inspect.getsource(models)
        for forbidden in ("fastapi", "pydantic", "sqlite3", "sqlglot", "app.adapters"):
            self.assertNotIn(forbidden, source.lower())

        ports = (
            AuditLogger,
            ContextResolver,
            DatabaseExecutor,
            LLMProvider,
            ResultFormatter,
            SQLGenerator,
            SQLSafetyChecker,
        )
        self.assertEqual(len(ports), 7)

    def test_api_layer_does_not_import_composition_root(self) -> None:
        from app.api import query

        source = inspect.getsource(query).lower()
        self.assertNotIn("app.bootstrap", source)


if __name__ == "__main__":
    unittest.main()
