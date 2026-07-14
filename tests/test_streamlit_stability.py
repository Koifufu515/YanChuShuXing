import html
import unittest
from unittest.mock import patch


class StreamlitStabilityTest(unittest.TestCase):
    def test_result_table_uses_safe_html_without_dataframe(self):
        from frontend import app

        with patch("frontend.app.st.dataframe") as dataframe, patch(
            "frontend.app.st.markdown"
        ) as markdown:
            app._show_result(
                {
                    "request_id": "req_table",
                    "sql": "SELECT 1",
                    "columns": ["customer_id", "note"],
                    "rows": [["C001", "<script>alert(1)</script>"]],
                    "summary": "查询成功。",
                    "warnings": [],
                    "error": None,
                },
                5,
            )

        dataframe.assert_not_called()
        rendered = " ".join(str(call.args[0]) for call in markdown.call_args_list)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>alert", rendered)

    def test_session_state_result_is_json_compatible_dict(self):
        from frontend import app

        stored = app._session_result(
            type("Result", (), {"payload": {"rows": [[2]]}, "elapsed_ms": 7})()
        )
        self.assertEqual(stored, {"payload": {"rows": [[2]]}, "elapsed_ms": 7})

    def test_failed_request_state_can_be_replaced_by_success(self):
        from frontend import app

        state = {"api_result": {"payload": {"error": {"code": "FAIL"}}, "elapsed_ms": 1}}
        state["api_result"] = app._session_result(
            type(
                "Result",
                (),
                {"payload": {"rows": [[2]], "error": None}, "elapsed_ms": 4},
            )()
        )
        self.assertIsNone(state["api_result"]["payload"]["error"])

    def test_technical_details_tolerate_missing_and_empty_metadata(self):
        from frontend import app

        self.assertEqual(app._technical_detail_rows(None)[0], ("运行模式", "未提供"))
        rows = dict(app._technical_detail_rows({"semantic": {}, "fallback": {}}))
        self.assertEqual(rows["实际执行器"], "未提供")
        self.assertEqual(rows["查询路径"], "未提供")
        self.assertEqual(rows["规则命中"], "未提供")
        self.assertEqual(rows["失败原因"], "无")
        self.assertEqual(rows["回退状态"], "未回退")

        routed = dict(
            app._technical_detail_rows(
                {
                    "route": "LLM",
                    "rule_matched": False,
                    "failure_reason": "unsafe_sql",
                    "semantic": {},
                    "fallback": {},
                }
            )
        )
        self.assertEqual(routed["查询路径"], "大模型路径")
        self.assertEqual(routed["规则命中"], "否")
        self.assertEqual(routed["失败原因"], "查询未通过安全校验")

    def test_technical_details_do_not_restore_dataframe(self):
        import inspect
        from frontend import app

        self.assertNotIn("st.dataframe", inspect.getsource(app))


if __name__ == "__main__":
    unittest.main()
