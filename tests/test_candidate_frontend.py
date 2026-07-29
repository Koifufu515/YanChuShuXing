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
        self.assertEqual(app_js.text.count('apiFetch("/api/v1/query"'), 2)
        self.assertNotIn('fetch("/api/v1/query"', app_js.text)

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
  ["机构", "说明", "数值"],
  [
    ["A银行", "包含,逗号", -123.45],
    ["B银行", "包含\"引号\"\n和换行", "普通文本"],
    ["C银行", "=SUM(1,2)", " +CMD"],
    ["D银行", "\t@HYPERLINK(...) ", "-1+2"]
  ]
);
if (!csv.startsWith("\uFEFF机构,说明,数值\r\n")) process.exit(1);
if (!csv.includes('"包含,逗号"')) process.exit(2);
if (!csv.includes('"包含""引号""\n和换行"')) process.exit(3);
if (!csv.includes('"\'=SUM(1,2)"')) process.exit(7);
if (!csv.includes("' +CMD")) process.exit(8);
if (!csv.includes("'\t@HYPERLINK(...) ")) process.exit(9);
if (!csv.includes("'-1+2")) process.exit(10);
if (!csv.includes(",-123.45")) process.exit(11);
if (csv.includes(",' -123.45") || csv.includes(",'-123.45")) process.exit(12);
if (!csv.includes("普通文本")) process.exit(13);
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

    def test_service_worker_preserves_unrelated_cache_namespaces(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/service-worker.js", "utf8");
const listeners = {};
const deleted = [];
const context = {
  URL,
  Promise,
  caches: {
    keys: async () => [
      "yanchushuxing-candidate-v1",
      "yanchushuxing-candidate-v2",
      "other-application-v9"
    ],
    delete: async key => { deleted.push(key); return true; },
    open: async () => ({ addAll: async () => {}, put: async () => {} }),
    match: async () => null,
  },
  self: {
    location: { origin: "https://example.test" },
    clients: { claim: async () => {} },
    skipWaiting() {},
    addEventListener(type, handler) { listeners[type] = handler; },
  },
};
vm.runInNewContext(source, context);
let activation;
listeners.activate({ waitUntil(promise) { activation = promise; } });
activation.then(() => {
  if (deleted.length !== 1 || deleted[0] !== "yanchushuxing-candidate-v1") process.exit(1);
  if (deleted.includes("other-application-v9")) process.exit(2);
  console.log(JSON.stringify({deleted}));
});
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout)["deleted"], ["yanchushuxing-candidate-v1"])

    def test_drawer_accessibility_state_focus_loop_and_desktop_reset(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/app.js", "utf8");
let desktop = false;
const classes = new Set();
const classList = {
  add(...names) { names.forEach(name => classes.add(name)); },
  remove(...names) { names.forEach(name => classes.delete(name)); },
  contains(name) { return classes.has(name); },
};
const document = { body: { classList }, activeElement: null };
function makeElement(name) {
  const attributes = new Map();
  return {
    name,
    inert: false,
    disabled: false,
    hidden: false,
    tabIndex: 0,
    focusables: [],
    setAttribute(key, value) { attributes.set(key, String(value)); },
    removeAttribute(key) { attributes.delete(key); },
    getAttribute(key) { return attributes.has(key) ? attributes.get(key) : null; },
    getClientRects() { return [{}]; },
    querySelectorAll() { return this.focusables; },
    contains(target) { return target === this || this.focusables.includes(target); },
    focus() { document.activeElement = this; },
  };
}
const conversation = makeElement("conversation");
const detail = makeElement("detail");
const conversationTrigger = makeElement("conversation-trigger");
const detailTrigger = makeElement("detail-trigger");
const center = makeElement("center");
const first = makeElement("first");
const last = makeElement("last");
conversation.focusables = [first, last];
detail.focusables = [makeElement("detail-first")];
const elements = {
  "#conversation-drawer": conversation,
  "#detail-drawer": detail,
  "#open-conversations": conversationTrigger,
  "#open-details": detailTrigger,
  ".center-panel": center,
};
document.querySelector = selector => elements[selector] || null;
const sandbox = {
  window: {
    addEventListener() {},
    matchMedia() { return {matches: desktop}; },
    YCSXResultAdapter: {},
  },
  requestAnimationFrame(callback) { callback(); },
  console,
  setTimeout,
  clearTimeout,
};
vm.runInNewContext(source, sandbox);
sandbox.document = document;
const utils = sandbox.window.YCSXCandidateUtils;
utils.syncDrawerAccessibility();
if (!conversation.inert || conversation.getAttribute("aria-hidden") !== "true") process.exit(1);
if (!detail.inert || detail.getAttribute("aria-hidden") !== "true") process.exit(2);
utils.openDrawer("conversation", conversationTrigger);
if (conversation.inert || conversation.getAttribute("aria-hidden") !== "false") process.exit(3);
if (conversation.getAttribute("role") !== "dialog" || conversation.getAttribute("aria-modal") !== "true") process.exit(4);
if (conversationTrigger.getAttribute("aria-expanded") !== "true" || !detail.inert || !center.inert) process.exit(5);
if (document.activeElement !== first) process.exit(6);
document.activeElement = last;
let prevented = false;
utils.trapDrawerFocus({key: "Tab", shiftKey: false, preventDefault() { prevented = true; }});
if (!prevented || document.activeElement !== first) process.exit(7);
document.activeElement = first;
prevented = false;
utils.trapDrawerFocus({key: "Tab", shiftKey: true, preventDefault() { prevented = true; }});
if (!prevented || document.activeElement !== last) process.exit(8);
utils.handleDrawerKeydown({key: "Escape", shiftKey: false, preventDefault() {}});
if (classes.has("drawer-open") || document.activeElement !== conversationTrigger) process.exit(9);
if (!conversation.inert || conversation.getAttribute("aria-hidden") !== "true" || center.inert) process.exit(10);
utils.openDrawer("detail", detailTrigger);
desktop = true;
utils.handleDrawerBreakpointChange({matches: true});
if (classes.has("drawer-open") || conversation.inert || detail.inert || center.inert) process.exit(11);
if (conversation.getAttribute("aria-hidden") !== null || detail.getAttribute("aria-modal") !== null) process.exit(12);
console.log(JSON.stringify({escapeRestored: true, desktopReset: true}));
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
            {"escapeRestored": True, "desktopReset": True},
        )

    def test_auth_session_headers_body_and_error_policy(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/app.js", "utf8");
function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
    snapshot() { return Object.fromEntries(values); },
  };
}
const sessionStorage = storage();
const localStorage = storage({ycsx_candidate_conversations_v1: "history-stays"});
const sandbox = {
  sessionStorage,
  localStorage,
  window: {addEventListener() {}, YCSXResultAdapter: {}},
  console,
  setTimeout,
  clearTimeout,
};
vm.runInNewContext(source, sandbox);
const utils = sandbox.window.YCSXCandidateUtils;
const anonymousHeaders = utils.buildApiHeaders({"Content-Type": "application/json"});
if (Object.prototype.hasOwnProperty.call(anonymousHeaders, "Authorization")) process.exit(1);
utils.setSessionToken("session-secret-token");
if (utils.getSessionToken() !== "session-secret-token") process.exit(2);
const authenticatedHeaders = utils.buildApiHeaders({"Content-Type": "application/json"});
if (authenticatedHeaders.Authorization !== "Bearer session-secret-token") process.exit(3);
if (localStorage.snapshot().ycsx_candidate_auth_token_v1) process.exit(4);
const body = utils.buildQueryBody("查询不良贷款率", "conversation-1");
if (JSON.stringify(body).includes("session-secret-token") || "token" in body || "authorization" in body) process.exit(5);
if (body.user_id !== "competition_demo_user") process.exit(6);
if (!utils.isAuthenticationError(401, {error: {code: "AUTHENTICATION_REQUIRED"}})) process.exit(7);
if (!utils.isAuthenticationError(401, {error: {code: "INVALID_AUTHENTICATION"}})) process.exit(8);
if (utils.isAuthenticationError(403, {error: {code: "ACCESS_DENIED"}})) process.exit(9);
const authentication = utils.authenticationPolicy(401, {error: {code: "INVALID_AUTHENTICATION"}});
if (!authentication.clearToken || !authentication.openDialog || authentication.retry) process.exit(10);
const authorization = utils.authenticationPolicy(403, {error: {code: "ACCESS_DENIED"}});
if (authorization.clearToken || authorization.openDialog || authorization.retry) process.exit(11);
const csv = utils.buildCsv(["指标"], [["普通结果"]]);
const copied = utils.analysisCopyText({payload: {}}, {summary: "普通摘要", structured: null});
if (`${csv}${copied}`.includes("session-secret-token")) process.exit(12);
utils.clearSessionToken();
if (utils.getSessionToken() !== null) process.exit(13);
if (localStorage.getItem("ycsx_candidate_conversations_v1") !== "history-stays") process.exit(14);
console.log(JSON.stringify({anonymousHeaders, authenticatedHeaders, body, history: localStorage.snapshot()}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertNotIn("Authorization", payload["anonymousHeaders"])
        self.assertEqual(
            payload["authenticatedHeaders"]["Authorization"],
            "Bearer session-secret-token",
        )
        self.assertEqual(
            payload["history"]["ycsx_candidate_conversations_v1"],
            "history-stays",
        )

    def test_auth_response_side_effects_clear_only_invalid_credentials(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/app.js", "utf8");
const values = new Map();
const sessionStorage = {
  getItem(key) { return values.has(key) ? values.get(key) : null; },
  setItem(key, value) { values.set(key, String(value)); },
  removeItem(key) { values.delete(key); },
};
function element() {
  return {
    open: false,
    disabled: false,
    textContent: "",
    value: "",
    setAttribute() {},
    focus() {},
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
}
const dialog = element();
const input = element();
const message = element();
const status = element();
const logout = element();
const openButton = element();
const elements = {
  "#auth-dialog": dialog,
  "#auth-token": input,
  "#auth-message": message,
  "#auth-status": status,
  "#auth-logout": logout,
  "#open-auth": openButton,
};
const document = {activeElement: openButton, querySelector(selector) { return elements[selector] || null; }};
const sandbox = {
  sessionStorage,
  window: {addEventListener() {}, YCSXResultAdapter: {}},
  requestAnimationFrame(callback) { callback(); },
  console,
  setTimeout,
  clearTimeout,
};
vm.runInNewContext(source, sandbox);
sandbox.document = document;
const utils = sandbox.window.YCSXCandidateUtils;
utils.setSessionToken("expired-secret");
const invalid = {error: {code: "INVALID_AUTHENTICATION", message: "raw"}};
utils.applyAuthenticationResponse(401, invalid);
if (utils.getSessionToken() !== null || !dialog.open) process.exit(1);
if (message.textContent.includes("expired-secret") || invalid.error.message.includes("expired-secret")) process.exit(2);
dialog.close();
utils.setSessionToken("still-valid-secret");
const denied = {error: {code: "ACCESS_DENIED", message: "raw"}};
utils.applyAuthenticationResponse(403, denied);
if (utils.getSessionToken() !== "still-valid-secret" || dialog.open) process.exit(3);
if (denied.error.message !== "当前账号无权访问相关机构或字段。") process.exit(4);
console.log(JSON.stringify({invalidMessage: invalid.error.message, deniedMessage: denied.error.message}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertIn("失效", payload["invalidMessage"])
        self.assertEqual(
            payload["deniedMessage"],
            "当前账号无权访问相关机构或字段。",
        )

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
        self.assertIn(".left-rail,.detail-panel{position:fixed;z-index:70", styles)
        self.assertIn(".drawer-scrim{display:block;position:fixed;z-index:55", styles)
        self.assertEqual(app_source.count('apiFetch("/api/v1/query"'), 2)
        self.assertNotIn('fetch("/api/v1/query"', app_source)
        self.assertIn("download.disabled = !view.columns.length || !view.rows.length", app_source)
        self.assertNotIn("localhost", app_source)
        self.assertIn('url.pathname.startsWith("/api/")', worker)
        self.assertIn('const CACHE_PREFIX = "yanchushuxing-candidate-"', worker)
        self.assertIn("key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME", worker)
        self.assertNotIn("keys.filter(key => key !== CACHE_NAME)", worker)
        self.assertIn("syncDrawerAccessibility", app_source)
        self.assertIn("trapDrawerFocus", app_source)
        self.assertIn('drawer.setAttribute("aria-hidden", open ? "false" : "true")', app_source)
        self.assertIn("drawer.inert = !open", app_source)
        self.assertIn('drawer.setAttribute("aria-modal", "true")', app_source)
        self.assertIn("centerPanel.inert = drawerOpen", app_source)
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/candidate")
        self.assertEqual({icon["purpose"] for icon in manifest["icons"]}, {"any", "maskable"})

    def test_auth_dialog_and_shared_request_contract_are_present(self) -> None:
        frontend = ROOT / "candidate_frontend"
        index = (frontend / "index.html").read_text("utf-8")
        app_source = (frontend / "app.js").read_text("utf-8")

        self.assertIn('<dialog id="auth-dialog"', index)
        self.assertIn('for="auth-token"', index)
        self.assertIn('id="auth-token" type="password"', index)
        self.assertIn("凭证仅保存在当前浏览器会话", index)
        self.assertIn('id="auth-connect"', index)
        self.assertIn('id="auth-cancel"', index)
        self.assertIn('id="auth-logout"', index)
        self.assertEqual(app_source.count('apiFetch("/api/v1/query"'), 2)
        self.assertNotIn('fetch("/api/v1/query"', app_source)
        self.assertIn("sessionStorage.setItem(AUTH_TOKEN_KEY", app_source)
        self.assertNotIn("localStorage.setItem(AUTH_TOKEN_KEY", app_source)
        self.assertNotIn("Authorization: Bearer", index)

    def test_security_alert_normalization_labels_counts_and_access_policy(self) -> None:
        script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("candidate_frontend/app.js", "utf8");
const storage = () => {
  const values = new Map();
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
};
const sandbox = {
  window: { addEventListener() {}, YCSXResultAdapter: {} },
  sessionStorage: storage(),
  localStorage: storage(),
  console,
  setTimeout,
  clearTimeout,
};
vm.runInNewContext(source, sandbox);
const utils = sandbox.window.YCSXCandidateUtils;
const payload = {
  request_id: "req-list",
  count: 4,
  alerts: [
    {occurred_at:"2026-07-29T09:00:00+00:00",alert_type:"repeated_authentication_failure",severity:"medium",event_count:5,window_seconds:60,security_action:"threshold",trigger_event_type:"authentication_failed",trigger_error_code:"INVALID_AUTHENTICATION",request_id:"req-1",actor_fingerprint:"abcdef123456",actor_sha256:"must-not-survive"},
    {occurred_at:"2026-07-29T09:01:00+00:00",alert_type:"repeated_institution_scope_denial",severity:"high",event_count:4,window_seconds:300,request_id:"req-2",actor_fingerprint:"123456abcdef"},
    {occurred_at:"2026-07-29T09:02:00+00:00",alert_type:"high_frequency_security_denial",severity:"critical",event_count:9,window_seconds:600,request_id:"req-3",actor_fingerprint:"fedcba654321"},
    {occurred_at:"bad-date",alert_type:"future_alert_type",severity:"unknown",event_count:1,window_seconds:75,request_id:"req-4",actor_fingerprint:"001122334455"}
  ]
};
const normalized = utils.normalizeSecurityAlertResponse(payload);
if (!normalized || normalized.requestId !== "req-list" || normalized.alerts.length !== 4) process.exit(1);
if (JSON.stringify(normalized).includes("must-not-survive") || "actor_sha256" in normalized.alerts[0]) process.exit(2);
const counts = utils.securityAlertCounts(normalized.alerts);
if (counts.total !== 4 || counts.medium !== 1 || counts.high !== 1 || counts.critical !== 1) process.exit(3);
if (utils.securityAlertTypeLabel("repeated_authentication_failure") !== "重复认证失败") process.exit(4);
if (utils.securityAlertTypeLabel("future_alert_type") !== "future_alert_type") process.exit(5);
if (utils.securitySeverityLabel("critical") !== "严重风险") process.exit(6);
if (utils.formatAlertWindow(60) !== "1 分钟" || utils.formatAlertWindow(300) !== "5 分钟" || utils.formatAlertWindow(75) !== "75 秒") process.exit(7);
if (utils.securityAlertAccessPolicy(401,{error:{code:"INVALID_AUTHENTICATION"}}).status !== "authentication_required") process.exit(8);
if (utils.securityAlertAccessPolicy(403,{error:{code:"ALERT_ACCESS_DENIED"}}).status !== "forbidden") process.exit(9);
if (utils.securityAlertAccessPolicy(200,payload).status !== "success") process.exit(10);
if (utils.normalizeSecurityAlertResponse({alerts:{}}) !== null) process.exit(11);
console.log(JSON.stringify({counts, unknown:utils.securityAlertTypeLabel("future_alert_type")}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["counts"]["critical"], 1)
        self.assertEqual(payload["unknown"], "future_alert_type")

    def test_security_center_is_manual_authenticated_and_memory_only(self) -> None:
        frontend = ROOT / "candidate_frontend"
        index = (frontend / "index.html").read_text("utf-8")
        app_source = (frontend / "app.js").read_text("utf-8")
        styles = (frontend / "styles.css").read_text("utf-8")

        self.assertIn('data-page="security"', index)
        self.assertIn("安全中心", index)
        self.assertIn('id="refresh-security-alerts"', index)
        self.assertIn('aria-live="polite"', index)
        self.assertEqual(
            app_source.count('apiFetch("/api/v1/security/alerts?limit=50"'),
            1,
        )
        self.assertNotIn("/api/v1/security/alerts?limit=50&", app_source)
        self.assertIn("applyAuthenticationResponse(response.status, payload)", app_source)
        self.assertIn('state.page === "security"', app_source)
        self.assertIn("state.fixtureMode", app_source)
        self.assertIn("securityStatus", app_source)
        self.assertNotIn("securityAlerts", app_source[app_source.index("function persist()"):app_source.index("function showToast")])
        self.assertNotIn("actor_sha256", index)
        self.assertNotIn("actor_sha256", app_source)
        self.assertNotIn("导出安全告警", index + app_source)
        self.assertIn("security-table-wrap", styles)
        self.assertIn("overflow-x:auto", styles)
        self.assertIn("security-overview", styles)
        self.assertNotIn("session-secret-token", index)


if __name__ == "__main__":
    unittest.main()
