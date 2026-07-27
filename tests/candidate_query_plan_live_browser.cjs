const { chromium } = require("C:/Users/ABC/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

const edgePath = process.env.YCSX_EDGE_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const baseUrl = process.env.YCSX_CANDIDATE_URL || "http://127.0.0.1:8512/candidate";
const question = "江苏省G市农商行2026年1月底净利润率是多少？";
const ambiguousQuestion = "帮我看看江苏省A市农商行的贷款情况。";

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

  const clarificationContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await clarificationContext.addInitScript(() => localStorage.clear());
  const clarificationPage = await clarificationContext.newPage();
  const clarificationRequests = [];
  clarificationPage.on("request", request => {
    if (new URL(request.url()).pathname === "/api/v1/query") clarificationRequests.push(request.postDataJSON());
  });
  await clarificationPage.goto(baseUrl, { waitUntil: "networkidle" });
  await clarificationPage.locator("#question").fill(ambiguousQuestion);
  const firstClarificationResponse = clarificationPage.waitForResponse(
    response => new URL(response.url()).pathname === "/api/v1/query",
    { timeout: 70000 },
  );
  await clarificationPage.locator("#question").press("Enter");
  const clarificationPayload = await (await firstClarificationResponse).json();
  await clarificationPage.locator('[data-clarification-field="metric"]').first().waitFor({ state: "visible", timeout: 10000 });
  await clarificationPage.locator('[data-clarification-field="query_date"]').fill("2025-12-31");
  await clarificationPage.locator('[data-clarification-field="metric"][value="ZB002"]').check({ force: true });
  const confirmationResponse = clarificationPage.waitForResponse(
    response => new URL(response.url()).pathname === "/api/v1/query",
    { timeout: 70000 },
  );
  await clarificationPage.getByRole("button", { name: "确认并查询" }).click();
  const confirmedPayload = await (await confirmationResponse).json();
  await clarificationPage.getByText("33.95 亿元", { exact: true }).waitFor({ state: "visible", timeout: 10000 });
  const clarificationBodyText = await clarificationPage.locator("body").innerText();
  const clarificationFields = (clarificationPayload.questions || []).map(item => item.field).sort();
  if (clarificationRequests.length !== 2) failures.push(`clarification flow expected two requests, got ${clarificationRequests.length}`);
  if (clarificationFields.join(",") !== "metric,query_date") failures.push(`unexpected clarification fields: ${clarificationFields.join(",")}`);
  if (clarificationBodyText.includes("增长方式")) failures.push("clarification page contains growth method");
  if (!clarificationRequests[1]?.clarification_id) failures.push("confirmation request has no clarification_id");
  if (clarificationRequests[1]?.question !== ambiguousQuestion) failures.push("confirmation request lost the original question");
  if (clarificationRequests[1]?.clarification_answers?.metric !== "ZB002") failures.push("confirmation request lost metric answer");
  if (clarificationRequests[1]?.clarification_answers?.query_date !== "2025-12-31") failures.push("confirmation request lost date answer");
  if (confirmedPayload?.metadata?.query_plan?.status?.code !== "executable") failures.push("confirmed query plan was not executable");
  report.dynamic_clarification = {
    request_count: clarificationRequests.length,
    first_status: clarificationPayload.status,
    fields: clarificationFields,
    second_request: clarificationRequests[1],
    final_status: confirmedPayload.status,
    final_rows: confirmedPayload.rows,
    growth_method_absent: !clarificationBodyText.includes("增长方式"),
  };
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  if (failures.length) throw new Error(failures.join("; "));
})().catch(error => {
  console.error(error.stack || String(error));
  process.exit(1);
});
