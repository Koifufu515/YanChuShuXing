const { chromium } = require("C:/Users/ABC/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const edgePath = process.env.YCSX_EDGE_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const baseUrl = process.env.YCSX_CANDIDATE_URL || "http://127.0.0.1:8512/candidate";
const question = "江苏省G市农商行2026年1月底，净利润率（净利润除以营业收入）是多少？";

(async () => {
  const browser = await chromium.launch({ executablePath: edgePath, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(() => localStorage.clear());
  const page = await context.newPage();
  const queryRequests = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname === "/api/v1/query") {
      queryRequests.push({ url: request.url(), method: request.method(), body: request.postDataJSON() });
    }
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator("#question").fill(question);
  const responsePromise = page.waitForResponse(
    response => new URL(response.url()).pathname === "/api/v1/query",
    { timeout: 70000 },
  );
  await page.locator("#question").press("Enter");
  await page.getByText("正在理解问题并查询数据……").waitFor({ state: "visible", timeout: 3000 });
  const disabledDuringRequest = await page.locator("#send").isDisabled();
  const response = await responsePromise;
  const payload = await response.json();
  await page.getByText("51.73 %", { exact: true }).waitFor({ state: "visible", timeout: 10000 });
  const bodyText = await page.locator("body").innerText();
  const inputEnabledAfterRequest = await page.locator("#send").isEnabled();

  const failures = [];
  if (queryRequests.length !== 1) failures.push(`expected one query request, got ${queryRequests.length}`);
  if (queryRequests[0]?.body?.question !== question) failures.push("request did not contain the original question");
  if (queryRequests[0]?.body?.confirmation) failures.push("frontend sent a local confirmation payload");
  if (!disabledDuringRequest) failures.push("submit button was not disabled during request");
  if (!inputEnabledAfterRequest) failures.push("submit button did not recover after request");
  for (const forbidden of ["还需确认", "增长方式", "全部13家机构", "全部13家正式机构"]) {
    if (bodyText.includes(forbidden)) failures.push(`page contains forbidden text: ${forbidden}`);
  }
  if (payload?.metadata?.query_plan?.status?.code !== "executable") failures.push("query plan was not executable");
  if (payload?.rows?.[0]?.[0] !== 51.73 || payload?.rows?.[0]?.[1] !== "%") failures.push("response was not 51.73%");

  const report = {
    request_count: queryRequests.length,
    request: queryRequests[0],
    response_status: response.status(),
    query_plan_status: payload?.metadata?.query_plan?.status?.code,
    provider: payload?.metadata?.provider,
    executed_generator: payload?.metadata?.executed_generator,
    route: payload?.metadata?.route,
    rows: payload?.rows,
    loading_visible: true,
    disabled_during_request: disabledDuringRequest,
    input_recovered: inputEnabledAfterRequest,
    page_shows_51_73_percent: bodyText.includes("51.73 %"),
    forbidden_text_absent: failures.filter(item => item.includes("forbidden text")).length === 0,
  };
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  if (failures.length) throw new Error(failures.join("; "));
})().catch(error => {
  console.error(error.stack || String(error));
  process.exit(1);
});
