from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

from app.adapters.audit.jsonl_logger import (
    JsonlAuditLogger,
)
from app.adapters.audit.noop_logger import (
    NoOpAuditLogger,
)
from app.api.query import (
    get_query_audit_logger,
    get_query_pipeline,
)
from app.bootstrap import container
from app.core.settings import Settings


def settings_for(
    *,
    data_environment: str,
) -> Settings:
    with patch.dict(
        "os.environ",
        {
            "BANKINSIGHT_DATA_ENV": (
                data_environment
            ),
            "BANKINSIGHT_LLM_API_KEY": (
                "test_key"
            ),
        },
        clear=False,
    ):
        return Settings.from_env(
            Path("/tmp/nonexistent.env")
        )


class ContainerAuditWiringTest(
    unittest.TestCase
):
    def tearDown(self) -> None:
        container.get_settings.cache_clear()
        container.get_audit_logger.cache_clear()
        container.get_pipeline.cache_clear()

    def test_real_environment_builds_jsonl_logger(
        self,
    ) -> None:
        logger = container.build_audit_logger(
            settings_for(
                data_environment="real",
            )
        )

        self.assertIsInstance(
            logger,
            JsonlAuditLogger,
        )
        self.assertEqual(
            logger.path,
            (
                container.PROJECT_ROOT
                / "data"
                / "private"
                / "audit"
                / "query_audit.jsonl"
            ),
        )

    def test_demo_environment_builds_noop_logger(
        self,
    ) -> None:
        logger = container.build_audit_logger(
            settings_for(
                data_environment="demo",
            )
        )

        self.assertIsInstance(
            logger,
            NoOpAuditLogger,
        )

    def test_audit_logger_is_cached_singleton(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            fake_settings = settings_for(
                data_environment="demo",
            )

            with patch.object(
                container,
                "get_settings",
                return_value=fake_settings,
            ):
                first = (
                    container
                    .get_audit_logger()
                )
                second = (
                    container
                    .get_audit_logger()
                )

        self.assertIs(
            first,
            second,
        )

    def test_fastapi_dependencies_use_container_providers(
        self,
    ) -> None:
        test_app = FastAPI()

        container.configure_dependencies(
            test_app
        )

        self.assertIs(
            test_app.dependency_overrides[
                get_query_pipeline
            ],
            container.get_pipeline,
        )
        self.assertIs(
            test_app.dependency_overrides[
                get_query_audit_logger
            ],
            container.get_audit_logger,
        )


if __name__ == "__main__":
    unittest.main()
