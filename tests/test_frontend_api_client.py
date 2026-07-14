import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError


SUCCESS_PAYLOAD = {
    "request_id": "req_demo",
    "question": "查询有效客户数量",
    "sql": "SELECT COUNT(*) FROM customer_info",
    "columns": ["customer_count"],
    "rows": [[2]],
    "summary": "当前共有2户有效客户。",
    "warnings": [],
    "error": None,
}


class _Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class FrontendAPIClientTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_query_posts_v1_contract_and_returns_payload(self, urlopen):
        from frontend.api_client import BankInsightClient

        urlopen.return_value = _Response(SUCCESS_PAYLOAD)
        result = BankInsightClient("http://127.0.0.1:8000").query("查询有效客户数量")

        request = urlopen.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/api/v1/query")
        self.assertEqual(sent["question"], "查询有效客户数量")
        self.assertEqual(sent["user_id"], "demo_user")
        self.assertEqual(result.payload["rows"], [[2]])
        self.assertGreaterEqual(result.elapsed_ms, 0)

    @patch("urllib.request.urlopen")
    def test_structured_api_error_is_returned_for_display(self, urlopen):
        from frontend.api_client import BankInsightClient

        payload = {
            **SUCCESS_PAYLOAD,
            "sql": None,
            "rows": [],
            "summary": None,
            "error": {
                "code": "UNSUPPORTED_QUESTION",
                "message": "首版暂不支持该问题。",
                "retryable": False,
            },
        }
        urlopen.side_effect = HTTPError(
            "http://127.0.0.1:8000/api/v1/query",
            400,
            "Bad Request",
            {},
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

        result = BankInsightClient("http://127.0.0.1:8000").query("查询贷款余额")

        self.assertEqual(result.payload["error"]["code"], "UNSUPPORTED_QUESTION")

    @patch("urllib.request.urlopen", side_effect=URLError("connection refused"))
    def test_connection_failure_becomes_safe_frontend_error(self, _urlopen):
        from frontend.api_client import APIConnectionError, BankInsightClient

        with self.assertRaisesRegex(APIConnectionError, "无法连接"):
            BankInsightClient("http://127.0.0.1:1").query("问题")

    @patch("urllib.request.urlopen")
    def test_same_client_recovers_after_connection_failure(self, urlopen):
        from frontend.api_client import APIConnectionError, BankInsightClient

        urlopen.side_effect = [URLError("connection refused"), _Response(SUCCESS_PAYLOAD)]
        client = BankInsightClient("http://127.0.0.1:8000")
        with self.assertRaises(APIConnectionError):
            client.query("查询有效客户数量")
        recovered = client.query("查询有效客户数量")
        self.assertEqual(recovered.payload["rows"], [[2]])


if __name__ == "__main__":
    unittest.main()
