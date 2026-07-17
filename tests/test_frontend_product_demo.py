import inspect
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendProductDemoTest(unittest.TestCase):
    def test_overview_metrics_are_read_from_demo_database(self):
        from frontend.kpi_repository import load_overview_metrics

        metrics = dict(
            load_overview_metrics(ROOT / "data" / "processed" / "bankinsight.db")
        )
        self.assertEqual(
            metrics,
            {"有效客户数": 2, "账户数量": 4, "交易总数": 4, "理财产品数": 0},
        )

    def test_overview_metrics_fail_safely_for_missing_database(self):
        from frontend.kpi_repository import load_overview_metrics

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(OSError):
                load_overview_metrics(Path(temp_dir) / "missing.db")

    def test_result_columns_and_values_are_product_friendly_chinese(self):
        from frontend import app

        rendered = app._result_table_html(
            ["customer_id", "account_balance"], [["C001", 6_000_000]]
        )
        self.assertIn("客户编号", rendered)
        self.assertIn("账户余额", rendered)
        self.assertIn("600.00 万元", rendered)
        self.assertNotIn(">account_balance<", rendered)

    def test_result_sections_follow_product_order(self):
        from frontend import app

        source = inspect.getsource(app._show_result)
        self.assertLess(source.index("业务结论"), source.index("关键指标"))
        self.assertLess(source.index("关键指标"), source.index("查询结果"))
        self.assertLess(source.index("查询结果"), source.index("生成 SQL"))
        self.assertLess(source.index("生成 SQL"), source.rindex("_show_technical_details"))

    def test_recommendations_are_data_driven_and_include_six_questions(self):
        from frontend import app

        questions = app.SCENARIOS["经营分析"]["questions"]
        self.assertEqual(len(questions), 6)
        self.assertIn("六月净流入最高的客户是谁？", questions)
        source = inspect.getsource(app._show_recommended_questions)
        self.assertIn("range(0, len(questions), 3)", source)

    def test_all_business_scenarios_have_complete_product_copy(self):
        from frontend import app

        self.assertEqual(tuple(app.SCENARIOS), app.BUSINESS_MODULES)
        for name, scenario in app.SCENARIOS.items():
            with self.subTest(name=name):
                self.assertTrue(scenario["icon"].startswith(":material/"))
                self.assertTrue(scenario["description"])
                self.assertTrue(scenario["placeholder"])
                self.assertGreaterEqual(len(scenario["questions"]), 3)
        self.assertTrue(app.SCENARIOS["经营分析"]["available"])
        self.assertTrue(app.SCENARIOS["客户分析"]["available"])
        self.assertFalse(app.SCENARIOS["贷款分析"]["available"])

    def test_scenario_switch_clears_stale_question_and_result(self):
        from frontend import app

        original_state = app.st.session_state
        try:
            app.st.session_state = {
                "selected_scenario": "经营分析",
                "question": "旧问题",
                "api_result": {"payload": {}},
            }
            app._select_scenario("客户分析")
            self.assertEqual(app.st.session_state["selected_scenario"], "客户分析")
            self.assertEqual(app.st.session_state["question"], "")
            self.assertNotIn("api_result", app.st.session_state)
        finally:
            app.st.session_state = original_state

    def test_scenario_selector_updates_copy_and_recommendations(self):
        from streamlit.testing.v1 import AppTest

        app_test = AppTest.from_file(str(ROOT / "frontend" / "app.py")).run()
        self.assertEqual(app_test.session_state["selected_scenario"], "经营分析")
        self.assertEqual(app_test.exception, [])

        app_test.button(key="scenario_贷款分析").click().run()
        self.assertEqual(app_test.session_state["selected_scenario"], "贷款分析")
        self.assertIn("贷款分析问题", app_test.text_area(key="question").proto.placeholder)
        self.assertTrue(
            any("后续版本" in item.value for item in app_test.markdown)
        )
        recommendations = [
            button.label
            for button in app_test.button
            if button.key and str(button.key).startswith("recommend_")
        ]
        self.assertIn("本月新增贷款金额是多少？", recommendations)
        self.assertEqual(app_test.exception, [])

    def test_streamlit_chrome_is_hidden_by_config_and_css(self):
        config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('toolbarMode = "minimal"', config)
        self.assertIn('showErrorDetails = "none"', config)
        from frontend import app

        style_source = inspect.getsource(app._apply_style)
        for selector in ("stHeader", "stToolbar", "MainMenu", "footer"):
            self.assertIn(selector, style_source)

    def test_frontend_preserves_native_stability_guards(self):
        from frontend import app

        source = inspect.getsource(app)
        self.assertIn('ARROW_DEFAULT_MEMORY_POOL", "system"', source)
        self.assertNotIn("st.dataframe", source)
        stored = app._session_result(
            type("Result", (), {"payload": {"rows": [[2]]}, "elapsed_ms": 6})()
        )
        self.assertEqual(stored, {"payload": {"rows": [[2]]}, "elapsed_ms": 6})


if __name__ == "__main__":
    unittest.main()
