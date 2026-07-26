from __future__ import annotations

import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "candidate_frontend"
RESULT_TYPES = ("单值", "跨期比较", "排名", "多机构对比", "趋势", "衍生指标", "综合分析")


class CandidateFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (CANDIDATE / "index.html").read_text(encoding="utf-8")
        cls.css = (CANDIDATE / "styles.css").read_text(encoding="utf-8")
        cls.javascript = (CANDIDATE / "app.js").read_text(encoding="utf-8")
        cls.contract = json.loads(
            (CANDIDATE / "result_contract.json").read_text(encoding="utf-8")
        )

    def test_candidate_is_served_from_the_api_origin(self) -> None:
        client = TestClient(app)
        page = client.get("/candidate")
        asset = client.get("/candidate/assets/result_contract.json")
        self.assertEqual(page.status_code, 200)
        self.assertIn("三栏", page.text)
        self.assertEqual(asset.status_code, 200)
        self.assertNotIn("access-control-allow-origin", page.headers)

    def test_layout_has_three_named_regions_and_fixed_desktop_ratio(self) -> None:
        for marker in (
            'data-testid="left-rail"',
            'data-testid="chat-panel"',
            'data-testid="detail-panel"',
            'data-testid="message-scroll"',
            'data-testid="fixed-composer"',
        ):
            self.assertIn(marker, self.html)
        self.assertIn("grid-template-columns:18% 52% 30%", self.css)
        self.assertIn("position:fixed", self.css)
        self.assertIn("overflow:auto", self.css)

    def test_seven_result_types_share_the_python_contract(self) -> None:
        self.assertEqual(tuple(self.contract["result_types"]), RESULT_TYPES)
        charts = self.contract["result_types"]
        self.assertEqual(charts["趋势"]["chart"], "line")
        self.assertEqual(charts["排名"]["chart"], "bar")
        self.assertEqual(charts["单值"]["chart"], "none")

    def test_query_and_conversation_behavior_use_existing_contract(self) -> None:
        self.assertIn('fetch("/api/v1/query"', self.javascript)
        self.assertIn('fetch("/api/v1/examples"', self.javascript)
        self.assertIn("conversation_id:conversation.id", self.javascript)
        self.assertIn("localStorage.setItem(STORAGE_KEY", self.javascript)
        self.assertIn("localStorage.getItem(STORAGE_KEY", self.javascript)
        self.assertIn("data-turn-index", self.javascript)

    def test_error_states_and_missing_fields_are_explicit(self) -> None:
        for code in (
            "CLARIFICATION_REQUIRED",
            "UNSUPPORTED_QUESTION",
            "ACCESS_DENIED",
            "SQL_REJECTED",
            "QUERY_TIMEOUT",
            "DATABASE_UNAVAILABLE",
        ):
            self.assertIn(code, self.contract["error_states"])
        self.assertIn("暂未提供", self.javascript)
        self.assertIn("生成的 SQL（默认折叠）", self.javascript)

    def test_untrusted_values_use_text_content_not_html_injection(self) -> None:
        self.assertIn("element.textContent = String(text)", self.javascript)
        self.assertNotIn("innerHTML", self.javascript)
        self.assertNotIn("insertAdjacentHTML", self.javascript)
        self.assertNotIn("Access-Control-Allow-Origin", self.javascript)

    def test_dashboard_is_limited_to_real_usage_statistics(self) -> None:
        for label in ("历史会话数量", "累计问数次数", "成功返回次数"):
            self.assertIn(label, self.javascript)
        self.assertIn("不代表银行经营数据", self.javascript)

    def test_fixture_mode_is_visibly_disclosed(self) -> None:
        self.assertIn("截图验收模式", self.javascript)
        self.assertIn("不是银行真实数据", self.javascript)
        self.assertNotIn("fixture", self.html.split("candidate-banner", 1)[0])


if __name__ == "__main__":
    unittest.main()
