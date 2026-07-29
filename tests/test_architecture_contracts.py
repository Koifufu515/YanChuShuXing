import inspect
from pathlib import Path
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

    def test_application_layer_does_not_import_adapters(
        self,
    ) -> None:
        application_root = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "app"
            / "application"
        )
        violations = []

        for module_path in sorted(
            application_root.rglob("*.py")
        ):
            module_source = (
                module_path.read_text(
                    encoding="utf-8"
                )
                .lower()
            )

            if "app.adapters" in module_source:
                violations.append(
                    module_path.name
                )

        self.assertEqual(
            violations,
            [],
            (
                "application层不能反向依赖"
                f"adapters层：{violations}"
            ),
        )

    def test_api_layer_does_not_import_composition_root(self) -> None:
        from app.api import query

        source = inspect.getsource(query).lower()
        self.assertNotIn("app.bootstrap", source)


if __name__ == "__main__":
    unittest.main()
