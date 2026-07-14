import unittest
from unittest.mock import patch


class FrontendViewTest(unittest.TestCase):
    @patch("frontend.app.st.markdown")
    @patch("frontend.app.st.dataframe")
    @patch("frontend.app.st.code")
    @patch("frontend.app.st.warning")
    def test_warning_is_displayed_from_api_payload(
        self, warning, _code, _dataframe, _markdown
    ):
        from frontend import app

        app._show_result(
            {
                "request_id": "req_warning",
                "sql": "SELECT 1",
                "columns": ["value"],
                "rows": [[1]],
                "summary": "查询成功。",
                "warnings": ["结果已截断。"],
                "error": None,
            },
            12,
        )

        warning.assert_called_once_with("结果已截断。")

    @patch("frontend.app._show_technical_details")
    @patch("frontend.app.st.markdown")
    @patch("frontend.app.st.error")
    def test_structured_error_is_displayed_without_internal_details(
        self, error, _markdown, technical_details
    ):
        from frontend import app

        app._show_result(
            payload := {
                "request_id": "req_error",
                "warnings": [],
                "metadata": {
                    "route": "LLM",
                    "rule_matched": False,
                    "failure_reason": "unsafe_sql",
                },
                "error": {
                    "code": "UNSUPPORTED_QUESTION",
                    "message": "首版暂不支持该问题。",
                    "retryable": False,
                },
            },
            8,
        )

        error.assert_called_once_with(
            "首版暂不支持该问题。"
        )
        technical_details.assert_called_once_with(payload["metadata"], payload, 8)


if __name__ == "__main__":
    unittest.main()
