from __future__ import annotations

import unittest

from app.main import app


class SessionMainWiringTest(
    unittest.TestCase
):
    def test_main_app_registers_session_route(
        self,
    ) -> None:
        paths = set(
            app.openapi().get("paths", {})
        )

        self.assertIn(
            "/api/v1/session/me",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
