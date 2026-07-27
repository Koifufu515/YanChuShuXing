(function () {
  "use strict";

  const STORAGE_KEY = "ycsx_candidate_conversations_v1";
  const ACTIVE_KEY = "ycsx_candidate_active_v1";
  const USER_ID = "competition_demo_user";
  const REQUEST_TIMEOUT_MS = 60000;
  const $ = (selector) => document.querySelector(selector);
  const adapter = window.YCSXResultAdapter;
  const chartInstances = new Set();
  const state = { contract: null, conversations: [], activeId: null, selectedTurn: null, page: "chat", busy: false, suggestions: [] };

  window.addEventListener("resize", () => chartInstances.forEach(chart => chart.resize()));

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function valueOrMissing(value) {
    if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return "暂未提供";
    if (Array.isArray(value)) return value.join("、");
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
  }

  function loadConversations() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      state.conversations = Array.isArray(parsed) ? parsed.filter(item => item && Array.isArray(item.turns)) : [];
    } catch (_) { state.conversations = []; }
    state.activeId = localStorage.getItem(ACTIVE_KEY) || state.conversations[0]?.id || null;
    if (!state.conversations.some(item => item.id === state.activeId)) state.activeId = state.conversations[0]?.id || null;
    const active = activeConversation();
    state.selectedTurn = active?.turns?.length ? active.turns.length - 1 : null;
  }

  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.conversations.slice(0, 200)));
    if (state.activeId) localStorage.setItem(ACTIVE_KEY, state.activeId);
  }

  function activeConversation() { return state.conversations.find(item => item.id === state.activeId) || null; }
  function makeId(prefix) { return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`; }

  function createConversation(title = "新会话") {
    const now = new Date().toISOString();
    const conversation = { id: makeId("conv"), title, createdAt: now, updatedAt: now, turns: [] };
    state.conversations.unshift(conversation);
    state.activeId = conversation.id;
    state.selectedTurn = null;
    state.page = "chat";
    persist();
    render();
    $("#question").focus();
    return conversation;
  }

  function dateLabel(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const today = new Date();
    if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  }

  function renderHistory() {
    const root = $("#history-list");
    const query = $("#history-search").value.trim().toLocaleLowerCase("zh-CN");
    const items = state.conversations.filter(item => !query || `${item.title} ${item.turns.map(turn => turn.question).join(" ")}`.toLocaleLowerCase("zh-CN").includes(query));
    $("#history-count").textContent = String(state.conversations.length);
    root.replaceChildren();
    if (!items.length) { root.append(node("div", "empty-list", query ? "没有匹配的会话" : "暂无历史会话")); return; }
    items.forEach(item => {
      const button = node("button", `history-item${item.id === state.activeId ? " active" : ""}`);
      button.type = "button";
      button.dataset.conversationId = item.id;
      button.append(node("strong", "", item.title));
      button.append(node("time", "", dateLabel(item.updatedAt)));
      button.append(node("small", "", `${item.turns.length} 轮对话`));
      root.append(button);
    });
  }

  function inferResultType(payload) {
    const explicit = payload?.metadata?.result_type || payload?.result_type;
    if (state.contract.result_types[explicit]) return explicit;
    const answerType = payload?.metadata?.query_plan?.output?.answer_type;
    const resultTypes = {
      single_value: "单值",
      comparison: "跨期比较",
      time_series: "趋势",
      ranking: "排名",
      extreme_value: "排名",
      boolean_with_difference: "跨期比较",
      threshold_assessment: "单值",
      composite: "综合分析",
    };
    return resultTypes[answerType] || "单值";
  }

  function queryPlan(payload) { return payload?.metadata?.query_plan || null; }
  function queryPlanStatus(payload) { return queryPlan(payload)?.status?.code || null; }

  function buildView(payload) {
    const resultType = inferResultType(payload || {});
    const columns = Array.isArray(payload?.columns) ? payload.columns.map(String) : [];
    const rows = Array.isArray(payload?.rows) ? payload.rows.filter(Array.isArray) : [];
    let chart = payload?.metadata?.chart_type || state.contract.result_types[resultType]?.chart || "none";
    if (!columns.length || !rows.length) chart = "none";
    return { resultType, chart, columns, rows, summary: payload?.summary || "当前结果暂无可用结论。", model: adapter.adapt(payload) };
  }

  function renderWelcome(root) {
    const box = node("section", "welcome");
    box.append(node("span", "bot-avatar", "AI"));
    box.append(node("h2", "", "你好，我是银行经营分析助手"));
    box.append(node("p", "", "直接提问指标数值、跨期变化、机构排名、趋势或综合分析。"));
    const suggestions = node("div", "suggestions");
    state.suggestions.forEach(question => {
      const button = node("button", "suggestion", question); button.type = "button"; button.dataset.question = question; suggestions.append(button);
    });
    if (state.suggestions.length) box.append(suggestions);
    else box.append(node("p", "", "正式业务目录暂未就绪，请先完成数据库初始化。"));
    root.append(box);
  }

  function makeTable(view) {
    const wrap = node("div", "result-table-wrap");
    const table = node("table"); const thead = node("thead"); const trh = node("tr");
    view.columns.forEach(column => trh.append(node("th", "", column))); thead.append(trh); table.append(thead);
    const tbody = node("tbody");
    view.rows.forEach(row => { const tr = node("tr"); view.columns.forEach((_, index) => tr.append(node("td", "", valueOrMissing(row[index])))); tbody.append(tr); });
    table.append(tbody); wrap.append(table); return wrap;
  }

  function disposeCharts() {
    chartInstances.forEach(chart => { try { chart.dispose(); } catch (_) {} });
    chartInstances.clear();
  }

  function makeChart(view) {
    const option = adapter.chartOption(view, view.model);
    if (!option || !window.echarts) return null;
    const kind = view.chart === "bar" ? "ranking" : "trend";
    const wrap = node("div", `chart echarts-chart ${kind}`);
    wrap.dataset.echarts = kind;
    wrap.__ycsxOption = option;
    wrap.setAttribute("role", "img");
    wrap.setAttribute("aria-label", `${view.resultType}图表`);
    return wrap;
  }

  function mountCharts(root) {
    root.querySelectorAll("[data-echarts]").forEach(element => {
      const option = element.__ycsxOption;
      if (!option) return;
      const { __audit, ...echartsOption } = option;
      const chart = window.echarts.init(element, null, { renderer: "svg" });
      chart.setOption(echartsOption, true);
      chartInstances.add(chart);
    });
  }

  function backendClarificationItems(payload) {
    const candidates=[payload?.questions,payload?.confirmation?.questions];
    return candidates.find(Array.isArray)||[];
  }

  function clarificationComplete(items, answers) {
    return !items.some(item=>item.required!==false&&(answers?.[item.field]===undefined||answers?.[item.field]===""||answers?.[item.field]?.length===0));
  }

  function renderClarification(turn,index,payload) {
    const status=queryPlan(payload)?.status||{};
    const box=node("section","confirmation-card");
    const intro=node("div","confirmation-intro");
    intro.append(node("strong","","需要补充查询条件"));
    box.append(intro);
    const original=node("p","confirmation-original");original.append(node("span","","原问题"),document.createTextNode(turn.question));box.append(original);
    box.append(node("p","confirmation-summary",status.clarification_question||status.reason||payload?.error?.message||"后端暂未提供具体补充说明。"));
    const items=backendClarificationItems(payload);
    if(items.length){
      const fields=node("div","confirmation-fields");
      items.forEach(item=>{
        const row=node("div","confirmation-field");
        const head=node("span","confirmation-label");head.append(node("strong","",item.label||item.field||"待确认项"));if(item.reason)head.append(node("small","",item.reason));row.append(head);
        const current=turn.clarificationAnswers?.[item.field];
        if(item.type==="single_select"||item.type==="multi_select"){
          const options=node("div","confirmation-options");
          (item.options||[]).forEach(option=>{const choice=node("label","confirmation-option");const input=document.createElement("input");input.type=item.type==="multi_select"?"checkbox":"radio";input.name=`clarification-${index}-${item.field}`;input.value=option.value;input.dataset.clarificationField=item.field;input.dataset.turnIndex=String(index);input.dataset.answerType=item.type;input.checked=item.type==="multi_select"?Array.isArray(current)&&current.includes(option.value):current===option.value;choice.append(input,node("span","",option.label));options.append(choice);});
          row.append(options);
        }else if(item.type==="date"){
          const input=node("input","confirmation-select");input.type="date";input.dataset.clarificationField=item.field;input.dataset.turnIndex=String(index);input.dataset.answerType=item.type;input.value=current||"";row.append(input);
        }else if(item.type==="text"){
          const input=node("textarea","confirmation-select");input.dataset.clarificationField=item.field;input.dataset.turnIndex=String(index);input.dataset.answerType=item.type;input.value=current||"";input.maxLength=500;row.append(input);
        }
        fields.append(row);
      });
      box.append(fields);
    }
    const actions=node("div","confirmation-actions");
    const confirm=node("button","primary confirmation-submit","确认并查询");confirm.type="button";confirm.dataset.confirmTurn=String(index);confirm.disabled=!clarificationComplete(items,turn.clarificationAnswers);
    const edit=node("button","ghost confirmation-edit","修改问题");edit.type="button";edit.dataset.editTurn=String(index);
    actions.append(confirm,edit);box.append(actions);
    return box;
  }

  function renderAnswer(turn, index) {
    const row = node("article", "message assistant"); row.append(node("span", "bot-avatar", "AI"));
    const card = node("div", `answer-card${state.selectedTurn === index ? " selected" : ""}`); card.dataset.turnIndex = String(index); card.tabIndex=0;
    const top = node("div", "answer-top"); top.append(node("strong", "", "AI 分析助手"));
    if (turn.pending) { top.append(node("span", "result-chip", "查询中")); top.append(node("small", "", "正在连接真实服务")); card.append(top); const body=node("div","answer-body"); body.append(node("p","answer-summary","正在理解问题并查询数据……")); card.append(body); row.append(card); return row; }
    const payload = turn.payload || {}; const view = buildView(payload); const planStatus=queryPlanStatus(payload); const waiting=planStatus==="clarification_required"; top.append(node("span", "result-chip", waiting?"待补充":(payload.error ? "未完成" : view.resultType))); top.append(node("small", "", `${Number(turn.elapsedMs || 0)} ms`)); card.append(top);
    const body = node("div", "answer-body");
    if(waiting){ body.append(renderClarification(turn,index,payload)); }
    else if(planStatus==="data_unavailable"){
      const status=queryPlan(payload)?.status||{};const error=node("div","error-card");error.append(node("strong","","数据暂不可用"));error.append(node("span","",status.reason||payload.error?.message||"后端暂未提供具体缺失条件。"));body.append(error);
    }
    else if (payload.error) {
      const spec = state.contract.error_states[payload.error.code] || ["查询失败", "查询未完成，请稍后重试。"]; const error = node("div", "error-card"); error.append(node("strong", "", spec[0])); error.append(node("span", "", payload.error.message || spec[1])); body.append(error);
    } else {
      body.append(node("p", "answer-summary", view.summary));
      if (view.resultType === "单值") { const single=adapter.singleValue(view.model); if(single){ const grid=node("div","kpi-grid"); const item=node("div","kpi"); item.append(node("span","",single.metricName)); item.append(node("strong","",single.valueText)); grid.append(item); body.append(grid); } }
      const chart = makeChart(view); if (chart) body.append(chart);
      if (view.rows.length>1) body.append(makeTable(view)); else if(!view.rows.length) body.append(node("p", "", "本次查询没有返回数据明细。"));
    }
    card.append(body); row.append(card); return row;
  }

  function renderMessages() {
    const root = $("#message-scroll"); disposeCharts(); root.replaceChildren(); const conversation = activeConversation();
    $("#page-title").textContent = conversation?.title || "新会话";
    if (!conversation || !conversation.turns.length) renderWelcome(root);
    else conversation.turns.forEach((turn, index) => { const user=node("article","message user"); const bubble=node("div","bubble"); bubble.append(node("p","",turn.question)); user.append(bubble,node("span","human-avatar","你")); root.append(user,renderAnswer(turn,index)); });
    requestAnimationFrame(() => { mountCharts(root); root.scrollTop = root.scrollHeight; });
  }

  function kv(parent, label, value) { const row=node("div","kv"); row.append(node("span","",label),node("strong","",valueOrMissing(value))); parent.append(row); }
  function renderDetails() {
    const root=$("#detail-content"); root.replaceChildren(); const conversation=activeConversation(); const turn=conversation?.turns?.[state.selectedTurn];
    if (!turn || turn.pending) { $("#detail-status").textContent=turn?.pending?"查询中":"未查询"; root.append(node("div","detail-empty",turn?.pending?"查询完成后将在这里显示执行信息。":"点击一条 AI 回答查看对应执行详情。")); return; }
    const payload=turn.payload||{}, view=buildView(payload), metadata=payload.metadata||{}, plan=metadata.query_plan||{}, security=metadata.security||{};
    $("#detail-status").textContent=payload.error?"未完成":"已返回";
    const overview=node("section","detail-group"); overview.append(node("h3","","本轮概览")); kv(overview,"查询耗时",metadata.query_duration_ms==null?"暂未提供":`${metadata.query_duration_ms} ms`); kv(overview,"完整响应",`${Number(turn.elapsedMs||0)} ms`); kv(overview,"结果类型",view.resultType); kv(overview,"推荐图表",view.chart==="none"?"无需图表":view.chart); kv(overview,"请求编号",payload.request_id); root.append(overview);
    const understanding=node("section","detail-group"); understanding.append(node("h3","","系统理解")); kv(understanding,"指标",plan.metrics?.requested_metric_ids); kv(understanding,"机构",plan.institutions?.targets?.map(item=>item.institution_id)); kv(understanding,"时间",plan.time); kv(understanding,"分析操作",plan.operations?.map(item=>item.operator_id)); root.append(understanding);
    if(plan.status){const confirmed=node("section","detail-group");confirmed.append(node("h3","","查询规划状态"));kv(confirmed,"状态",plan.status.code);kv(confirmed,"说明",plan.status.clarification_question||plan.status.reason);root.append(confirmed);}
    const source=node("section","detail-group"); source.append(node("h3","","数据与执行")); kv(source,"数据来源",metadata.data_source || metadata.executor); kv(source,"执行路径",metadata.route || metadata.executed_generator || metadata.query_path); root.append(source);
    const details=node("details","sql-details"); details.append(node("summary","","生成的 SQL（默认折叠）")); details.append(node("pre","",valueOrMissing(payload.sql))); root.append(details);
    const safe=node("section","detail-group"); safe.append(node("h3","","安全与审计")); kv(safe,"权限状态",security.permission || metadata.permission_status); kv(safe,"脱敏状态",security.masking || metadata.masking_status); kv(safe,"审计状态",security.audit || metadata.audit_status); root.append(safe);
  }

  function renderDashboard() {
    const root=$("#dashboard-view"); root.replaceChildren();
    const all=state.conversations.flatMap(item=>item.turns); const complete=all.filter(turn=>!turn.pending); const success=complete.filter(turn=>turn.payload&&!turn.payload.error).length;
    root.append(node("div","dashboard-note","这里只展示当前浏览器真实保存的系统使用统计，不代表银行经营数据。"));
    const grid=node("div","dashboard-grid"); [["历史会话数量",state.conversations.length],["累计问数次数",complete.length],["成功返回次数",success]].forEach(([label,value])=>{const card=node("article","dashboard-card");card.append(node("span","",label),node("strong","",value));grid.append(card);}); root.append(grid);
    const recent=node("section","recent"); recent.append(node("h2","","最近查询记录"));
    const recentTurns=state.conversations.flatMap(conversation=>conversation.turns.map(turn=>({...turn,conversationTitle:conversation.title}))).sort((a,b)=>String(b.createdAt).localeCompare(String(a.createdAt))).slice(0,8);
    if (!recentTurns.length) recent.append(node("div","empty-list","暂无真实查询记录")); else recentTurns.forEach(turn=>{const row=node("div","recent-row");row.append(node("span","",turn.question),node("time","",dateLabel(turn.createdAt)));recent.append(row);}); root.append(recent);
  }

  function setPage(page) {
    state.page=page; document.querySelectorAll("[data-page]").forEach(button=>button.classList.toggle("active",button.dataset.page===page));
    document.querySelector(".workbench").classList.toggle("dashboard-mode",page==="dashboard");
    $("#chat-view").hidden=page!=="chat"; $("#dashboard-view").hidden=page!=="dashboard"; $("#detail-content").parentElement.hidden=page!=="chat";
    $("#page-title").textContent=page==="dashboard"?"数据看板":activeConversation()?.title||"新会话"; $("#page-subtitle").textContent=page==="dashboard"?"当前浏览器的真实使用统计":"用自然语言查询银行经营数据"; $("#head-new-chat").hidden=page!=="chat";
    if(page==="dashboard")renderDashboard();
  }

  function render() { renderHistory(); renderMessages(); renderDetails(); setPage(state.page); }

  async function postQuery(body, signal) {
    const response=await fetch("/api/v1/query",{method:"POST",headers:{"Content-Type":"application/json"},signal,body:JSON.stringify(body)});
    let payload;try{payload=await response.json();}catch(_){payload={error:{code:"INVALID_RESPONSE",message:"服务返回了无法识别的内容。",retryable:true},columns:[],rows:[]};}
    if(!response.ok&&!payload.error)payload.error={code:`HTTP_${response.status}`,message:"查询服务暂时未完成请求。",retryable:response.status>=500};
    return payload;
  }

  async function submitQuestion(question) {
    const text=question.trim(); if(text.length<2||state.busy)return;
    let conversation=activeConversation(); if(!conversation) conversation=createConversation(text.slice(0,36)); if(!conversation.turns.length) conversation.title=text.slice(0,36);
    const turn={question:text,pending:true,createdAt:new Date().toISOString(),elapsedMs:0,payload:null}; conversation.turns.push(turn); conversation.updatedAt=turn.createdAt; state.selectedTurn=conversation.turns.length-1; state.busy=true; persist(); render(); $("#send").disabled=true;
    const started=performance.now(); const controller=new AbortController(); const timeoutId=setTimeout(()=>controller.abort(),REQUEST_TIMEOUT_MS);
    try {
      turn.payload=await postQuery({question:text,user_id:USER_ID,conversation_id:conversation.id},controller.signal);
    } catch (error) { const timedOut=error?.name==="AbortError";turn.payload={question:text,columns:[],rows:[],warnings:[],error:{code:timedOut?"QUERY_TIMEOUT":"NETWORK_ERROR",message:timedOut?"查询时间较长，请稍后重试。":"无法连接言出数行服务，请确认后端已经启动。",retryable:true},metadata:null}; }
    finally { clearTimeout(timeoutId); }
    turn.elapsedMs=Math.max(1,Math.round(performance.now()-started)); turn.pending=false; conversation.updatedAt=new Date().toISOString(); state.busy=false; persist(); $("#send").disabled=false; render();
  }

  async function confirmTurn(index) {
    const conversation=activeConversation(),turn=conversation?.turns?.[index],payload=turn?.payload||{};
    const clarificationId=payload.clarification_id||payload.confirmation?.clarification_id;
    if(!turn||!clarificationId||state.busy)return;
    turn.pending=true;state.busy=true;state.selectedTurn=index;persist();render();$("#send").disabled=true;
    const started=performance.now(),controller=new AbortController(),timeoutId=setTimeout(()=>controller.abort(),REQUEST_TIMEOUT_MS);
    try{
      turn.payload=await postQuery({question:turn.question,user_id:USER_ID,conversation_id:conversation.id,clarification_id:clarificationId,clarification_answers:{...(turn.clarificationAnswers||{})}},controller.signal);
    }catch(error){const timedOut=error?.name==="AbortError";turn.payload={question:turn.question,columns:[],rows:[],warnings:[],error:{code:timedOut?"QUERY_TIMEOUT":"NETWORK_ERROR",message:timedOut?"查询时间较长，请稍后重试。":"无法连接言出数行服务，请确认后端已经启动。",retryable:true},metadata:null};}
    finally{clearTimeout(timeoutId);}
    turn.elapsedMs=Math.max(1,Math.round(performance.now()-started));turn.pending=false;conversation.updatedAt=new Date().toISOString();state.busy=false;persist();$("#send").disabled=false;render();
  }

  function installFixture() {
    const params=new URLSearchParams(location.search); const fixture=params.get("fixture"); if(!fixture)return;
    const badge=node("div","fixture-banner",`截图验收模式 · ${fixture} · 数值为明确标注的界面 fixture，不是银行真实数据`); document.body.append(badge);
    const now=new Date().toISOString();
    const fixtures={
      empty:null,
      trend:{question:"演示：最近七天指标趋势",summary:"验收 fixture：指标总体呈上升趋势，仅用于检查图表排版。",columns:["日期","演示值"],rows:[["07-20",82],["07-21",91],["07-22",88],["07-23",104],["07-24",110],["07-25",106],["07-26",121]],sql:"SELECT demo_date, demo_value FROM screenshot_fixture",warnings:["验收 fixture，不代表真实业务结果"],error:null,request_id:"fixture_trend",metadata:{result_type:"趋势",chart_type:"line",data_source:"验收 fixture",semantic:{metrics:["演示指标"],time_range:{start:"07-20",end:"07-26"}},security:{audit:"不适用（fixture）"}}},
      history:{question:"演示：本月指标是多少？",summary:"验收 fixture：本月演示值为 121，仅用于检查历史会话恢复。",columns:["月份","演示值"],rows:[["本月",121]],sql:"SELECT demo_month, demo_value FROM screenshot_fixture",warnings:["验收 fixture，不代表真实业务结果"],error:null,request_id:"fixture_history_2",metadata:{result_type:"单值",data_source:"验收 fixture",semantic:{metrics:["演示指标"],time_range:{label:"本月"}},security:{audit:"不适用（fixture）"}}}
    };
    if(fixture==="empty"){state.conversations=[];state.activeId=null;state.selectedTurn=null;return;}
    const payload=fixtures[fixture]||fixtures.trend; const turns=fixture==="history"?[{question:fixtures.trend.question,payload:fixtures.trend,elapsedMs:128,createdAt:now,pending:false},{question:payload.question,payload,elapsedMs:96,createdAt:now,pending:false}]:[{question:payload.question,payload,elapsedMs:128,createdAt:now,pending:false}]; state.conversations=[{id:"fixture_conversation",title:fixture==="history"?"验收 fixture：已恢复会话":"验收 fixture：趋势图",createdAt:now,updatedAt:now,turns}]; state.activeId="fixture_conversation"; state.selectedTurn=turns.length-1; if(params.get("page")==="dashboard")state.page="dashboard";
  }

  function bind() {
    $("#new-chat").addEventListener("click",()=>createConversation()); $("#head-new-chat").addEventListener("click",()=>createConversation());
    $("#history-search").addEventListener("input",renderHistory);
    $("#history-list").addEventListener("click",event=>{const target=event.target.closest("[data-conversation-id]");if(!target)return;state.activeId=target.dataset.conversationId;const conversation=activeConversation();state.selectedTurn=conversation?.turns?.length?conversation.turns.length-1:null;state.page="chat";persist();render();});
    document.querySelector("nav").addEventListener("click",event=>{const target=event.target.closest("[data-page]");if(target)setPage(target.dataset.page);});
    const updateClarification=(event,rerender=true)=>{const input=event.target.closest("[data-clarification-field]");if(!input)return;const turn=activeConversation()?.turns?.[Number(input.dataset.turnIndex)];if(!turn)return;turn.clarificationAnswers={...(turn.clarificationAnswers||{})};const field=input.dataset.clarificationField;if(input.dataset.answerType==="multi_select"){const values=[...document.querySelectorAll(`[data-turn-index="${input.dataset.turnIndex}"] [data-clarification-field="${field}"]:checked`)].map(item=>item.value);if(values.length)turn.clarificationAnswers[field]=values;else delete turn.clarificationAnswers[field];}else if(input.value)turn.clarificationAnswers[field]=input.value;else delete turn.clarificationAnswers[field];persist();if(rerender){renderMessages();renderDetails();}else{const items=backendClarificationItems(turn.payload||{});const button=document.querySelector(`[data-confirm-turn="${input.dataset.turnIndex}"]`);if(button)button.disabled=!clarificationComplete(items,turn.clarificationAnswers);}};
    $("#message-scroll").addEventListener("change",event=>updateClarification(event,true));$("#message-scroll").addEventListener("input",event=>{if(event.target.dataset.answerType==="text")updateClarification(event,false);});
    $("#message-scroll").addEventListener("click",event=>{const confirm=event.target.closest("[data-confirm-turn]");if(confirm){confirmTurn(Number(confirm.dataset.confirmTurn));return;}const edit=event.target.closest("[data-edit-turn]");if(edit){const turn=activeConversation()?.turns?.[Number(edit.dataset.editTurn)];if(turn){$("#question").value=turn.question;$("#question").focus();}return;}const suggestion=event.target.closest("[data-question]");if(suggestion){$("#question").value=suggestion.dataset.question;submitQuestion(suggestion.dataset.question);return;}if(event.target.closest("[data-clarification-field],.confirmation-option"))return;const answer=event.target.closest("[data-turn-index]");if(answer){state.selectedTurn=Number(answer.dataset.turnIndex);renderMessages();renderDetails();}});
    $("#composer").addEventListener("submit",event=>{event.preventDefault();const field=$("#question");const question=field.value;field.value="";submitQuestion(question);});
    $("#question").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("#composer").requestSubmit();}});
  }

  async function initialize() {
    const response=await fetch("/candidate/assets/result_contract.json"); state.contract=await response.json();
    try { const examples=await fetch("/api/v1/examples"); const payload=await examples.json(); state.suggestions=(payload.examples||[]).map(item=>item.question).filter(Boolean); } catch (_) { state.suggestions=[]; }
    loadConversations(); installFixture(); bind(); render();
    const params=new URLSearchParams(location.search);
    const demoMode=params.get("real_demo");
    const demoIndex={single:0,ranking:1,trend:2,"1":1}[demoMode];
    if(Number.isInteger(demoIndex)&&!params.get("fixture")&&state.suggestions[demoIndex]){
      const demoNames={single:"单值",ranking:"机构排名",trend:"趋势"};
      createConversation(`真实数据库联调：${demoNames[demoMode]||"机构排名"}`);
      await submitQuestion(state.suggestions[demoIndex]);
    }
  }
  initialize().catch(()=>{document.body.replaceChildren(node("div","error-card","候选前端资源加载失败，请重新启动服务。"));});
})();
