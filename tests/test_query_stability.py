import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.query import get_query_pipeline
from app.bootstrap.container import build_pipeline
from app.core.settings import Settings


class QueryStabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.adapters.database.init_db import initialize_database
        from app.main import app

        cls.app = app
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.temp_dir.name) / "demo.db"
        initialize_database(
            cls.database_path,
            Path(__file__).resolve().parents[1] / "sql" / "schema.sql",
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        pipeline = build_pipeline(
            self.database_path,
            settings=Settings(generator_mode="rule"),
        )
        self.app.dependency_overrides[get_query_pipeline] = lambda: pipeline
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()

    def _post(self, question):
        return self.client.post(
            "/api/v1/query", json={"question": question, "user_id": "stability"}
        )

    def test_alternating_queries_twenty_times(self):
        questions = ("查询有效客户数量", "查询客户C001的账户余额")
        for index in range(20):
            response = self._post(questions[index % 2])
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json()["error"])

    def test_failure_then_success_recovers(self):
        failed = self._post("不支持的问题")
        recovered = self._post("查询有效客户数量")
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["rows"], [[2]])

    def test_three_fixed_questions_repeat_without_contract_drift(self):
        questions = (
            "查询有效客户数量",
            "查询客户C001的账户余额",
            "查询客户C001在2026年6月的交易汇总",
        )
        for index in range(30):
            response = self._post(questions[index % 3])
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIsNone(body["error"])
            self.assertTrue(body["rows"])


if __name__ == "__main__":
    unittest.main()
