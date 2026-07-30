import unittest
from unittest.mock import patch


class FrontendViewTest(unittest.TestCase):
    @patch("frontend.app._show_technical_details")
    @patch("frontend.app._render_answer_payload", return_value=True)
    def test_structured_answer_is_preferred(self, render_answer, _technical):
        from frontend import app

        answer = {
            "answer_type": "benchmark_comparison",
            "headline": "结构化结论",
            "summary": "结构化解释",
        }
        app._show_result(
            {
                "answer": answer,
                "summary": "旧摘要",
                "columns": ["legacy"],
                "rows": [[1]],
                "warnings": [],
                "error": None,
            },
            5,
        )

        render_answer.assert_called_once_with(answer)

    @patch("frontend.app.st.markdown")
    def test_chart_uses_values_from_chart_spec(self, markdown):
        from frontend import app

        rendered = app._render_chart_spec(
            {
                "chart_type": "bar",
                "title": "成本收入比对比",
                "categories": ["目标机构", "全省均值"],
                "series": [
                    {"name": "成本收入比", "values": [31.42, 36.96]}
                ],
                "unit": "%",
            }
        )

        self.assertTrue(rendered)
        html_payload = markdown.call_args.args[0]
        self.assertIn("31.42%", html_payload)
        self.assertIn("36.96%", html_payload)

    @patch("frontend.app.st.markdown")
    def test_structured_answer_renders_headline_evidence_chart_and_summary(
        self, markdown
    ):
        from frontend import app

        rendered = app._render_answer_payload(
            {
                "answer_type": "benchmark_comparison",
                "headline": "成本收入比低于全省均值5.54个百分点",
                "summary": "该行当前成本控制表现相对较好。",
                "key_metrics": [
                    {"label": "目标机构", "value": 31.42, "unit": "%"},
                    {"label": "全省均值", "value": 36.96, "unit": "%"},
                ],
                "table": {
                    "columns": ["比较对象", "成本收入比", "单位"],
                    "rows": [
                        ["目标机构", 31.42, "%"],
                        ["全省均值", 36.96, "%"],
                    ],
                },
                "chart_spec": {
                    "chart_type": "bar",
                    "title": "成本收入比对比",
                    "categories": ["目标机构", "全省均值"],
                    "series": [
                        {"name": "成本收入比", "values": [31.42, 36.96]}
                    ],
                    "unit": "%",
                },
            }
        )

        self.assertTrue(rendered)
        output = "\n".join(str(call.args[0]) for call in markdown.call_args_list)
        self.assertIn("低于全省均值5.54个百分点", output)
        self.assertIn("目标机构", output)
        self.assertIn("31.42%", output)
        self.assertIn("36.96%", output)
        self.assertIn("成本控制表现相对较好", output)

    @patch("frontend.app._show_technical_details")
    @patch("frontend.app._render_answer_payload", return_value=False)
    @patch("frontend.app.st.markdown")
    def test_null_answer_uses_legacy_result(
        self, markdown, render_answer, _technical
    ):
        from frontend import app

        app._show_result(
            {
                "answer": None,
                "summary": "旧摘要",
                "columns": ["value"],
                "rows": [[1]],
                "warnings": [],
                "error": None,
            },
            5,
        )

        render_answer.assert_called_once_with(None)
        self.assertTrue(
            any("旧摘要" in str(call.args[0]) for call in markdown.call_args_list)
        )

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
