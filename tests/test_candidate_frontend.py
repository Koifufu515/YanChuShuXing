import json
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


class CandidateFrontendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()

    def test_candidate_page_and_assets_are_served(self) -> None:
        page = self.client.get("/candidate")
        self.assertEqual(page.status_code, 200)
        self.assertIn("言出数行", page.text)

        app_js = self.client.get("/candidate/assets/app.js")
        self.assertEqual(app_js.status_code, 200)
        self.assertIn('fetch("/api/v1/query"', app_js.text)

        contract = self.client.get("/candidate/assets/result_contract.json")
        self.assertEqual(contract.status_code, 200)
        self.assertEqual(contract.json()["version"], 1)

    def test_structured_answer_has_priority_and_legacy_response_falls_back(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/result_adapter.js", "utf8");
const sandbox = { window: {} };
vm.runInNewContext(source, sandbox);
const adapter = sandbox.window.YCSXResultAdapter;
const payload = {
  summary: "旧摘要",
  columns: ["旧列"],
  rows: [[999]],
  answer: {
    answer_type: "benchmark_comparison",
    headline: "结构化标题",
    summary: "结构化摘要",
    key_metrics: [{label: "目标值", value: 31.42, unit: "%"}],
    table: {columns: ["对象", "值"], rows: [["目标机构", 31.42]]},
    chart_spec: {
      chart_type: "bar",
      title: "指标对比",
      categories: ["目标机构", "全省均值"],
      series: [{name: "成本收入比", values: [31.42, 36.96]}],
      unit: "%"
    }
  }
};
const answer = adapter.structuredAnswer(payload);
if (answer.headline !== "结构化标题" || answer.summary !== "结构化摘要") process.exit(1);
if (answer.table.rows[0][1] !== 31.42 || answer.keyMetrics[0].value !== 31.42) process.exit(2);
const option = adapter.chartSpecOption(answer.chartSpec);
if (option.series[0].data[1] !== 36.96 || option.xAxis.data[0] !== "目标机构") process.exit(3);
if (adapter.structuredAnswer({summary: "旧摘要", columns: [], rows: []}) !== null) process.exit(4);
console.log(JSON.stringify({headline: answer.headline, chart: option.series[0].type}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"headline": "结构化标题", "chart": "bar"},
        )

        app_source = (ROOT / "candidate_frontend" / "app.js").read_text("utf-8")
        self.assertIn("structured?.table?.columns", app_source)
        self.assertIn("structured?.summary || payload?.summary", app_source)
        self.assertLess(
            app_source.index("if (view.rows.length) body.append(makeTable(view));"),
            app_source.index("if (chart) body.append(chart);", app_source.index("if (view.structured)")),
        )


if __name__ == "__main__":
    unittest.main()
