from __future__ import annotations

import unittest

from fastapi import FastAPI

from app.api.permission_demo import (
    get_permission_demo_executor,
)
from app.bootstrap.container import (
    configure_dependencies,
)
from app.main import app


class PermissionDemoMainWiringTest(
    unittest.TestCase
):
    def test_main_app_registers_route(
        self,
    ) -> None:
        paths = set(
            app.openapi().get("paths", {})
        )

        self.assertIn(
            "/api/v1/security/demo-portfolio",
            paths,
        )

    def test_configure_dependencies_registers_executor(
        self,
    ) -> None:
        test_app = FastAPI()

        configure_dependencies(test_app)

        self.assertIn(
            get_permission_demo_executor,
            test_app.dependency_overrides,
        )


if __name__ == "__main__":
    unittest.main()
