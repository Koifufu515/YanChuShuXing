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

        manifest = self.client.get("/candidate/assets/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["start_url"], "/candidate")

        service_worker = self.client.get("/candidate/assets/service-worker.js")
        self.assertEqual(service_worker.status_code, 200)
        self.assertIn('url.pathname.startsWith("/api/")', service_worker.text)

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

    def test_export_helpers_escape_csv_and_exclude_internal_details(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/app.js", "utf8");
const sandbox = {
  window: { addEventListener() {}, YCSXResultAdapter: {} },
  console,
  setTimeout,
  clearTimeout,
};
vm.runInNewContext(source, sandbox);
const utils = sandbox.window.YCSXCandidateUtils;
const csv = utils.buildCsv(
  ["机构", "说明"],
  [["A银行", "包含,逗号"], ["B银行", "包含\"引号\"\n和换行"]]
);
if (!csv.startsWith("\uFEFF机构,说明\r\n")) process.exit(1);
if (!csv.includes('"包含,逗号"')) process.exit(2);
if (!csv.includes('"包含""引号""\n和换行"')) process.exit(3);
const filename = utils.exportFilename("机构/排名：分析？", new Date(2026, 6, 29, 9, 8, 7));
if (filename !== "机构 排名 分析-20260729-090807.csv") process.exit(4);
const copied = utils.analysisCopyText(
  {createdAt: "2026-07-29T01:00:00Z", payload: {request_id: "req-1", sql: "SECRET SQL"}},
  {structured: {headline: "结论标题"}, summary: "业务摘要"}
);
if (!copied.includes("结论标题") || !copied.includes("业务摘要") || !copied.includes("req-1")) process.exit(5);
if (copied.includes("SECRET SQL")) process.exit(6);
console.log(JSON.stringify({bom: csv.charCodeAt(0), filename, copied}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["bom"], 65279)
        self.assertEqual(payload["filename"], "机构 排名 分析-20260729-090807.csv")
        self.assertNotIn("SECRET SQL", payload["copied"])

    def test_mobile_pwa_and_export_contracts_are_present(self) -> None:
        frontend = ROOT / "candidate_frontend"
        index = (frontend / "index.html").read_text("utf-8")
        styles = (frontend / "styles.css").read_text("utf-8")
        app_source = (frontend / "app.js").read_text("utf-8")
        worker = (frontend / "service-worker.js").read_text("utf-8")
        manifest = json.loads((frontend / "manifest.webmanifest").read_text("utf-8"))

        self.assertIn('rel="manifest"', index)
        self.assertIn('aria-controls="conversation-drawer"', index)
        self.assertIn('aria-controls="detail-drawer"', index)
        self.assertIn("100dvh", styles)
        self.assertIn("@media(max-width:768px)", styles)
        self.assertIn("overflow-x:auto", styles)
        self.assertIn('fetch("/api/v1/query"', app_source)
        self.assertIn("download.disabled = !view.columns.length || !view.rows.length", app_source)
        self.assertNotIn("localhost", app_source)
        self.assertIn('url.pathname.startsWith("/api/")', worker)
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/candidate")
        self.assertEqual({icon["purpose"] for icon in manifest["icons"]}, {"any", "maskable"})


if __name__ == "__main__":
    unittest.main()
