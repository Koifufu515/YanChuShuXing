from __future__ import annotations

import unittest

from app.api.permission_demo import (
    get_permission_demo_executor,
)
from app.main import app


class PermissionDemoMainWiringTest(
    unittest.TestCase
):
    def test_main_app_registers_route(
        self,
    ) -> None:
        paths = {
            route.path
            for route in app.routes
        }

        self.assertIn(
            "/api/v1/security/demo-portfolio",
            paths,
        )

    def test_main_app_configures_executor(
        self,
    ) -> None:
        self.assertIn(
            get_permission_demo_executor,
            app.dependency_overrides,
        )


if __name__ == "__main__":
    unittest.main()
