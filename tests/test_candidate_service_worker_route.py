from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class CandidateServiceWorkerRouteTest(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_service_worker_is_served_under_candidate_scope(
        self,
    ) -> None:
        response = self.client.get(
            "/candidate/service-worker.js"
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertIn(
            "javascript",
            response.headers["content-type"],
        )
        self.assertEqual(
            response.headers[
                "service-worker-allowed"
            ],
            "/candidate",
        )
        self.assertEqual(
            response.headers["cache-control"],
            "no-cache",
        )
        self.assertIn(
            "yanchushuxing-candidate-",
            response.text,
        )

    def test_candidate_page_and_assets_remain_available(
        self,
    ) -> None:
        page = self.client.get("/candidate")
        script = self.client.get(
            "/candidate/assets/app.js"
        )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(script.status_code, 200)
        self.assertIn(
            "言出数行",
            page.text,
        )

    def test_service_worker_route_is_not_in_openapi(
        self,
    ) -> None:
        schema = self.client.get(
            "/openapi.json"
        ).json()

        self.assertNotIn(
            "/candidate/service-worker.js",
            schema["paths"],
        )


if __name__ == "__main__":
    unittest.main()
