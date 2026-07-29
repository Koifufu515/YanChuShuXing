(function () {
  "use strict";

  const STORAGE_KEY = "ycsx_candidate_conversations_v1";
  const ACTIVE_KEY = "ycsx_candidate_active_v1";
  const AUTH_TOKEN_KEY = "ycsx_candidate_auth_token_v1";
  const USER_ID = "competition_demo_user";
  const DESKTOP_DRAWER_QUERY = "(min-width: 1100px)";
  const FOCUSABLE_SELECTOR = 'a[href], button, input, select, textarea, summary, [contenteditable="true"], [tabindex]';
  const $ = (selector) => document.querySelector(selector);
  const adapter = window.YCSXResultAdapter;
  const chartInstances = new Set();
  const state = {
    contract: null,
    conversations: [],
    activeId: null,
    selectedTurn: null,
    page: "chat",
    busy: false,
    sessionProfile: null,
    sessionStatus: "idle",
    sessionError: null,
    suggestions: [],
    fixtureMode: false,
    securityAlerts: [],
    securityStatus: "idle",
    securityError: null,
    securityRequestId: null,
  };
  let drawerReturnFocus = null;
  let authDialogReturnFocus = null;
  let toastTimer = null;

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

  function csvEscape(value) {
    const protectedValue = typeof value === "string" && /^[ \t\r]*[=+\-@]/.test(value) ? `'${value}` : value;
    const text = protectedValue === null || protectedValue === undefined ? "" : String(protectedValue);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function buildCsv(columns, rows) {
    const lines = [columns, ...rows].map(row => row.map(csvEscape).join(","));
    return `\uFEFF${lines.join("\r\n")}`;
  }

  function safeFileStem(value) {
    const normalized = String(value || "分析结果")
      .replace(/[\\/:*?"<>|：？]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 28);
    return normalized || "分析结果";
  }

  function exportFilename(question, date = new Date()) {
    const pad = value => String(value).padStart(2, "0");
    const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
    return `${safeFileStem(question)}-${stamp}.csv`;
  }

  function analysisCopyText(turn, view) {
    const payload = turn?.payload || {};
    const headline = view?.structured?.headline || "分析结论";
    const lines = [headline, view?.summary || payload.summary || ""];
    if (turn?.createdAt) lines.push(`查询时间：${new Date(turn.createdAt).toLocaleString("zh-CN")}`);
    if (payload.request_id) lines.push(`请求编号：${payload.request_id}`);
    return lines.filter(Boolean).join("\n");
  }

  function getSessionToken() {
    try {
      const token = sessionStorage.getItem(AUTH_TOKEN_KEY);
      return token && token.trim() ? token.trim() : null;
    } catch (_) {
      return null;
    }
  }

  function setSessionToken(token) {
    const value = typeof token === "string" ? token.trim() : "";
    if (!value) return false;
    try {
      sessionStorage.setItem(AUTH_TOKEN_KEY, value);
      return true;
    } catch (_) {
      return false;
    }
  }

  function clearSessionToken() {
    try { sessionStorage.removeItem(AUTH_TOKEN_KEY); } catch (_) {}
  }

  function buildApiHeaders(baseHeaders = {}) {
    const headers = { ...baseHeaders };
    const token = getSessionToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  function buildQueryBody(question, conversationId, confirmation = null) {
    const body = { question, user_id: USER_ID, conversation_id: conversationId };
    if (confirmation) body.confirmation = confirmation;
    return body;
  }

  function apiFetch(url, options = {}) {
    return fetch(url, { ...options, headers: buildApiHeaders(options.headers || {}) });
  }

  function isAuthenticationError(status, payload) {
    const code = payload?.error?.code;
    return status === 401 || code === "AUTHENTICATION_REQUIRED" || code === "INVALID_AUTHENTICATION";
  }

  function authenticationPolicy(status, payload) {
    if (isAuthenticationError(status, payload)) {
      const invalid = payload?.error?.code === "INVALID_AUTHENTICATION" || Boolean(getSessionToken());
      return {
        clearToken: true,
        openDialog: true,
        retry: false,
        message: invalid
          ? "访问凭证无效或已经失效，请重新连接后手动发送问题。"
          : "缺少访问凭证，请连接后手动发送问题。",
      };
    }
    if (status === 403 || payload?.error?.code === "ACCESS_DENIED") {
      return {
        clearToken: false,
        openDialog: false,
        retry: false,
        message: "当前账号无权访问相关机构或字段。",
      };
    }
    return { clearToken: false, openDialog: false, retry: false, message: null };
  }

  function normalizeAccessScope(value) {
    const source = value && typeof value === "object" ? value : {};
    return {
      enforced: Boolean(source.enforced),
      allAccess: Boolean(source.all_access),
      ids: Array.isArray(source.ids)
        ? source.ids.map(item => String(item)).filter(Boolean)
        : [],
    };
  }

  function normalizeSessionProfile(payload) {
    if (!payload || typeof payload !== "object") return null;

    const subjectId = typeof payload.subject_id === "string"
      ? payload.subject_id.trim()
      : "";
    const displayName = typeof payload.display_name === "string"
      ? payload.display_name.trim()
      : "";
    const role = typeof payload.role === "string"
      ? payload.role.trim()
      : "";

    if (!subjectId || !displayName || !role) return null;

    const capabilities = payload.capabilities
      && typeof payload.capabilities === "object"
      ? payload.capabilities
      : {};

    return {
      requestId: typeof payload.request_id === "string"
        ? payload.request_id
        : "",
      subjectId,
      displayName,
      role,
      roleLabel: typeof payload.role_label === "string"
        && payload.role_label.trim()
        ? payload.role_label.trim()
        : role,
      authenticated: Boolean(payload.authenticated),
      maskingProfile: typeof payload.masking_profile === "string"
        ? payload.masking_profile
        : "none",
      institutionScope: normalizeAccessScope(
        payload.institution_scope
      ),
      relationshipManagerScope: normalizeAccessScope(
        payload.relationship_manager_scope
      ),
      capabilities: {
        canQuery: Boolean(capabilities.can_query),
        canViewPermissionDemo: Boolean(
          capabilities.can_view_permission_demo
        ),
        canViewSecurityAlerts: Boolean(
          capabilities.can_view_security_alerts
        ),
        rowScopeActive: Boolean(
          capabilities.row_scope_active
        ),
      },
    };
  }

  function sessionScopeSummary(
    scope,
    {
      allLabel = "全部",
      noneLabel = "未配置",
    } = {},
  ) {
    if (!scope || typeof scope !== "object") {
      return noneLabel;
    }
    if (scope.allAccess) return allLabel;
    if (Array.isArray(scope.ids) && scope.ids.length) {
      return scope.ids.join("、");
    }
    return scope.enforced ? "无授权范围" : noneLabel;
  }

  function sessionCapabilitySummary(capabilities) {
    if (!capabilities || typeof capabilities !== "object") {
      return "暂未提供";
    }

    const labels = [];
    if (capabilities.canQuery) labels.push("智能问数");
    if (capabilities.canViewPermissionDemo) {
      labels.push("权限演示");
    }
    if (capabilities.canViewSecurityAlerts) {
      labels.push("安全告警");
    }

    return labels.length ? labels.join("、") : "无可访问功能";
  }

  function renderSessionProfile() {
    if (typeof document === "undefined") return;

    const profile = state.sessionProfile;
    const connected = state.sessionStatus === "authenticated"
      && Boolean(profile);

    const name = $("#session-name");
    const role = $("#session-role");
    const avatar = $("#session-avatar");
    const profileBox = $("#session-profile");
    const securityNav = $("#security-nav");

    if (name) {
      name.textContent = connected
        ? profile.displayName
        : "比赛演示用户";
    }
    if (role) {
      role.textContent = connected
        ? `${profile.roleLabel} · ${profile.maskingProfile}`
        : state.sessionStatus === "loading"
          ? "正在验证访问凭证"
          : state.sessionStatus === "error"
            ? "身份验证失败"
            : "尚未验证身份";
    }
    if (avatar) {
      avatar.textContent = connected
        ? profile.displayName.slice(0, 1).toUpperCase()
        : "U";
    }

    if (securityNav) {
      const allowed = Boolean(
        connected
        && profile.capabilities.canViewSecurityAlerts
      );
      securityNav.disabled = !allowed;
      securityNav.setAttribute(
        "aria-disabled",
        String(!allowed),
      );
      securityNav.title = allowed
        ? "查看安全告警"
        : "当前身份无权查看安全告警";
    }

    if (!profileBox) return;

    profileBox.hidden = !connected;
    if (!connected) return;

    $("#session-subject").textContent = profile.subjectId;
    $("#session-role-label").textContent = (
      `${profile.roleLabel}（${profile.role}）`
    );
    $("#session-institution-scope").textContent = (
      sessionScopeSummary(
        profile.institutionScope,
        {
          allLabel: "全部机构",
          noneLabel: "未启用机构限制",
        },
      )
    );
    $("#session-rm-scope").textContent = (
      sessionScopeSummary(
        profile.relationshipManagerScope,
        {
          allLabel: "全部客户经理",
          noneLabel: "未配置行级范围",
        },
      )
    );
    $("#session-masking").textContent = (
      profile.maskingProfile
    );
    $("#session-capabilities").textContent = (
      sessionCapabilitySummary(profile.capabilities)
    );
  }

  function resetSessionProfile() {
    state.sessionProfile = null;
    state.sessionStatus = "idle";
    state.sessionError = null;
    if (typeof document !== "undefined") {
      renderSessionProfile();
    }
  }

  async function loadSessionProfile() {
    if (!getSessionToken()) {
      resetSessionProfile();
      updateAuthStatus();
      return null;
    }

    state.sessionStatus = "loading";
    state.sessionError = null;
    updateAuthStatus();

    try {
      const response = await apiFetch(
        "/api/v1/session/me"
      );

      let payload;
      try {
        payload = await response.json();
      } catch (_) {
        payload = {
          error: {
            code: "INVALID_RESPONSE",
            message: "身份服务返回了无法识别的内容。",
          },
        };
      }

      if (
        isAuthenticationError(
          response.status,
          payload,
        )
      ) {
        clearSessionToken();
      }

      if (!response.ok || payload?.error) {
        throw new Error(
          payload?.error?.message
          || "无法验证当前访问凭证。"
        );
      }

      const profile = normalizeSessionProfile(
        payload
      );

      if (!profile || !profile.authenticated) {
        throw new Error(
          "身份服务未返回有效的认证身份。"
        );
      }

      state.sessionProfile = profile;
      state.sessionStatus = "authenticated";
      state.sessionError = null;
      updateAuthStatus();

      return profile;
    } catch (error) {
      state.sessionProfile = null;
      state.sessionStatus = getSessionToken()
        ? "error"
        : "idle";
      state.sessionError = (
        error instanceof Error
          ? error.message
          : "无法验证当前访问凭证。"
      );
      updateAuthStatus();

      return null;
    }
  }

  function updateAuthStatus() {
    const hasToken = Boolean(getSessionToken());
    const connected = (
      state.sessionStatus === "authenticated"
      && Boolean(state.sessionProfile)
    );
    const status = $("#auth-status");
    const logout = $("#auth-logout");

    if (status) {
      status.textContent = (
        state.sessionStatus === "loading"
          ? "验证中"
          : connected
            ? "已连接"
            : hasToken
              ? "待验证"
              : "未连接"
      );
    }

    if (logout) logout.disabled = !hasToken;

    renderSessionProfile();
  }

  function openAuthDialog(message = "", trigger = null) {
    const dialog = $("#auth-dialog");
    const input = $("#auth-token");
    const messageBox = $("#auth-message");
    if (!dialog) return;
    authDialogReturnFocus = trigger || document.activeElement;
    if (input) input.value = "";
    if (messageBox) messageBox.textContent = message;
    updateAuthStatus();
    if (!dialog.open) dialog.showModal();
    requestAnimationFrame(() => input?.focus());
  }

  function applyAuthenticationResponse(status, payload) {
    const result = payload && typeof payload === "object" ? payload : {};
    const policy = authenticationPolicy(status, result);
    if (!policy.message) return result;
    if (!result.error || typeof result.error !== "object") result.error = {};
    result.error.code = result.error.code || (status === 403 ? "ACCESS_DENIED" : "AUTHENTICATION_REQUIRED");
    result.error.message = policy.message;
    result.error.retryable = false;
    if (policy.clearToken) {
      clearSessionToken();
      resetSessionProfile();
      updateAuthStatus();
    }
    if (policy.openDialog) openAuthDialog(policy.message);
    return result;
  }

  function logoutAuthSession() {
    clearSessionToken();
    resetSessionProfile();
    resetSecurityAlertState();
    updateAuthStatus();
    const input = $("#auth-token");
    if (input) input.value = "";
    $("#auth-dialog")?.close();
    showToast("已退出访问凭证会话");
  }

  function resetSecurityAlertState() {
    state.securityAlerts = [];
    state.securityStatus = "idle";
    state.securityError = null;
    state.securityRequestId = null;
    if (typeof document !== "undefined") renderSecurityCenter();
  }

  function securityAlertTypeLabel(value) {
    const labels = {
      repeated_authentication_failure: "重复认证失败",
      repeated_institution_scope_denial: "重复机构越权",
      high_frequency_security_denial: "高频安全拒绝",
    };
    const key = typeof value === "string" ? value.trim() : "";
    return labels[key] || key || "未知告警";
  }

  function securitySeverityLabel(value) {
    const labels = { medium: "中风险", high: "高风险", critical: "严重风险" };
    const key = typeof value === "string" ? value.trim().toLowerCase() : "";
    return labels[key] || key || "未知风险";
  }

  function formatAlertWindow(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) return "暂未提供";
    if (seconds > 0 && seconds % 60 === 0) return `${seconds / 60} 分钟`;
    return `${seconds} 秒`;
  }

  function normalizeSecurityAlertResponse(payload) {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.alerts)) return null;
    const alerts = payload.alerts.map(item => {
      const source = item && typeof item === "object" ? item : {};
      const numeric = value => Number.isFinite(Number(value)) ? Number(value) : 0;
      return {
        occurredAt: typeof source.occurred_at === "string" ? source.occurred_at : "",
        alertType: typeof source.alert_type === "string" ? source.alert_type : "",
        severity: typeof source.severity === "string" ? source.severity.toLowerCase() : "",
        eventCount: numeric(source.event_count),
        windowSeconds: numeric(source.window_seconds),
        securityAction: typeof source.security_action === "string" ? source.security_action : "",
        triggerEventType: typeof source.trigger_event_type === "string" ? source.trigger_event_type : "",
        triggerErrorCode: typeof source.trigger_error_code === "string" ? source.trigger_error_code : "",
        requestId: typeof source.request_id === "string" ? source.request_id : "",
        actorFingerprint: typeof source.actor_fingerprint === "string" ? source.actor_fingerprint : "",
      };
    });
    return {
      requestId: typeof payload.request_id === "string" ? payload.request_id : "",
      count: alerts.length,
      alerts,
    };
  }

  function securityAlertCounts(alerts) {
    const list = Array.isArray(alerts) ? alerts : [];
    return list.reduce((counts, alert) => {
      counts.total += 1;
      if (alert?.severity === "medium") counts.medium += 1;
      if (alert?.severity === "high") counts.high += 1;
      if (alert?.severity === "critical") counts.critical += 1;
      return counts;
    }, { total: 0, medium: 0, high: 0, critical: 0 });
  }

  function securityAlertAccessPolicy(status, payload) {
    const code = payload?.error?.code;
    if (isAuthenticationError(status, payload)) {
      return { status: "authentication_required", message: payload?.error?.message || "请连接访问凭证后手动刷新。" };
    }
    if (status === 403 || code === "ALERT_ACCESS_DENIED" || code === "ACCESS_DENIED") {
      return { status: "forbidden", message: "当前账号无权查看安全告警。" };
    }
    if (status >= 400 || payload?.error) {
      return { status: "error", message: "安全告警服务暂时无法完成请求。" };
    }
    return { status: "success", message: null };
  }

  window.YCSXCandidateUtils = Object.freeze({
    csvEscape,
    buildCsv,
    safeFileStem,
    exportFilename,
    analysisCopyText,
    syncDrawerAccessibility,
    openDrawer,
    closeDrawers,
    trapDrawerFocus,
    handleDrawerKeydown,
    handleDrawerBreakpointChange,
    getSessionToken,
    setSessionToken,
    clearSessionToken,
    buildApiHeaders,
    buildQueryBody,
    isAuthenticationError,
    authenticationPolicy,
    applyAuthenticationResponse,
    normalizeSessionProfile,
    sessionScopeSummary,
    sessionCapabilitySummary,
    loadSessionProfile,
    logoutAuthSession,
    securityAlertTypeLabel,
    securitySeverityLabel,
    formatAlertWindow,
    normalizeSecurityAlertResponse,
    securityAlertCounts,
    securityAlertAccessPolicy,
  });

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

  function showToast(message) {
    const toast = $("#toast");
    if (!toast) return;
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("visible");
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 1800);
  }

  function isDesktopLayout() {
    return typeof window.matchMedia === "function" && window.matchMedia(DESKTOP_DRAWER_QUERY).matches;
  }

  function drawerElements() {
    return [
      { drawer: $("#conversation-drawer"), trigger: $("#open-conversations"), openClass: "conversation-open" },
      { drawer: $("#detail-drawer"), trigger: $("#open-details"), openClass: "detail-open" },
    ];
  }

  function visibleFocusableElements(drawer) {
    if (!drawer) return [];
    return Array.from(drawer.querySelectorAll(FOCUSABLE_SELECTOR)).filter(element => {
      if (element.disabled || element.hidden || element.tabIndex === -1) return false;
      if (element.getAttribute("aria-hidden") === "true") return false;
      return typeof element.getClientRects !== "function" || element.getClientRects().length > 0;
    });
  }

  function syncDrawerAccessibility() {
    const desktop = isDesktopLayout();
    let drawerOpen = false;

    drawerElements().forEach(({ drawer, trigger, openClass }) => {
      if (!drawer) return;
      const open = !desktop && document.body.classList.contains(openClass);
      drawerOpen ||= open;
      trigger?.setAttribute("aria-expanded", String(open));

      if (desktop) {
        drawer.inert = false;
        drawer.removeAttribute("aria-hidden");
        drawer.removeAttribute("role");
        drawer.removeAttribute("aria-modal");
        return;
      }

      drawer.inert = !open;
      drawer.setAttribute("aria-hidden", open ? "false" : "true");
      if (open) {
        drawer.setAttribute("role", "dialog");
        drawer.setAttribute("aria-modal", "true");
      } else {
        drawer.removeAttribute("role");
        drawer.removeAttribute("aria-modal");
      }
    });

    const centerPanel = $(".center-panel");
    if (centerPanel) centerPanel.inert = drawerOpen;
  }

  function activeDrawer() {
    if (isDesktopLayout()) return null;
    if (document.body.classList.contains("conversation-open")) return $("#conversation-drawer");
    if (document.body.classList.contains("detail-open")) return $("#detail-drawer");
    return null;
  }

  function trapDrawerFocus(event) {
    if (event.key !== "Tab") return false;
    const drawer = activeDrawer();
    if (!drawer) return false;
    const focusable = visibleFocusableElements(drawer);
    if (!focusable.length) {
      event.preventDefault();
      return true;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
      return true;
    }
    if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
      return true;
    }
    return false;
  }

  function handleDrawerKeydown(event) {
    if ($("#auth-dialog")?.open) return false;
    if (event.key === "Escape" && document.body.classList.contains("drawer-open")) {
      closeDrawers();
      return true;
    }
    return trapDrawerFocus(event);
  }

  function handleDrawerBreakpointChange(event) {
    if (event.matches) closeDrawers(false);
    else syncDrawerAccessibility();
  }

  function closeDrawers(restoreFocus = true) {
    document.body.classList.remove("conversation-open", "detail-open", "drawer-open");
    syncDrawerAccessibility();
    if (restoreFocus && drawerReturnFocus && typeof drawerReturnFocus.focus === "function") drawerReturnFocus.focus();
    drawerReturnFocus = null;
  }

  function openDrawer(kind, trigger) {
    closeDrawers(false);
    drawerReturnFocus = trigger || document.activeElement;
    document.body.classList.add(`${kind}-open`, "drawer-open");
    const drawerSelector = kind === "conversation" ? "#conversation-drawer" : "#detail-drawer";
    syncDrawerAccessibility();
    requestAnimationFrame(() => visibleFocusableElements($(drawerSelector))[0]?.focus());
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
    const semantic = payload?.metadata?.semantic || {};
    const text = `${semantic.intent || ""} ${payload?.question || ""}`.toLowerCase();
    if (/趋势|逐月|逐季|走势|trend/.test(text)) return "趋势";
    if (/排名|最高|最低|top|ranking|排第/.test(text)) return "排名";
    if (/同比|环比|较去年|上季度|上个月|变化|变动|增幅/.test(text)) return "跨期比较";
    if (/占比|比例|存贷比|人均|日均|计算|derived/.test(text)) return "衍生指标";
    if (/综合|分析|多维|overview/.test(text)) return "综合分析";
    if (/多机构|多家|各机构|机构对比/.test(text) || ((semantic.dimensions || []).some(item => ["institution", "institution_id", "机构"].includes(String(item))))) return "多机构对比";
    return "单值";
  }

  function buildView(payload) {
    const structured = adapter.structuredAnswer(payload);
    const resultType = structured?.resultType || inferResultType(payload || {});
    const legacyTable = adapter.displayTable(payload);
    const columns = structured?.table?.columns || legacyTable.columns;
    const rows = structured?.table?.rows || legacyTable.rows;
    let chart;
    if (structured) {
      chart = structured.chartSpec?.chart_type || "none";
    } else {
      chart = payload?.metadata?.chart_type || state.contract.result_types[resultType]?.chart || "none";
    }
    if (!columns.length || !rows.length) chart = "none";

    if (!structured) {
      const unitIndex = columns.findIndex(
        column => column === "单位" || column === "unit"
      );

      if (unitIndex >= 0) {
        const distinctUnits = new Set(
          rows
            .map(row => row[unitIndex])
            .filter(
              unit =>
                unit !== null
                && unit !== undefined
                && String(unit).trim() !== ""
            )
            .map(unit => String(unit))
        );

        if (distinctUnits.size > 1) {
          chart = "none";
        }
      }
    }
    return { resultType, chart, columns, rows, summary: structured?.summary || payload?.summary || "当前结果暂无可用结论。", structured, model: adapter.adapt(payload) };
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

  function makeResultActions(turn, view, index) {
    const actions = node("div", "result-actions");
    const copy = node("button", "result-action", "复制分析结论");
    copy.type = "button";
    copy.dataset.copyTurn = String(index);
    const download = node("button", "result-action", "导出 CSV");
    download.type = "button";
    download.dataset.exportTurn = String(index);
    download.disabled = !view.columns.length || !view.rows.length;
    download.title = download.disabled ? "当前结果没有可导出的表格" : "导出当前回答展示的数据";
    actions.append(copy, download);
    return actions;
  }

  async function copyAnalysis(index) {
    const turn = activeConversation()?.turns?.[index];
    if (!turn?.payload || turn.payload.error) return;
    const text = analysisCopyText(turn, buildView(turn.payload));
    try {
      await navigator.clipboard.writeText(text);
      showToast("分析结论已复制");
    } catch (_) {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.append(field);
      field.select();
      const copied = document.execCommand("copy");
      field.remove();
      showToast(copied ? "分析结论已复制" : "复制失败，请稍后重试");
    }
  }

  function exportCurrentTable(index) {
    const turn = activeConversation()?.turns?.[index];
    if (!turn?.payload || turn.payload.error) return;
    const view = buildView(turn.payload);
    if (!view.columns.length || !view.rows.length) return;
    const blob = new Blob([buildCsv(view.columns, view.rows)], { type: "text/csv;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = exportFilename(turn.question);
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(href);
    showToast("CSV 已导出");
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

  const confirmationStateLabels = { recognized:"已识别", needs_confirmation:"需要确认", missing:"缺少条件", unrecognized:"未识别" };

  function finalConditionsText(confirmation) {
    const values=confirmation?.final_conditions||{};
    const period=values.comparison_period||{};
    return [values.metric?.label,values.analysis?.label,values.growth_method?.label,period.start_date&&period.end_date?`${period.start_date} 至 ${period.end_date}`:null,values.institution_scope?.label].filter(Boolean).join("；");
  }

  function renderConfirmation(turn,index,payload) {
    const confirmation=payload.confirmation||{};
    const box=node("section","confirmation-card");
    const visibleFields=(confirmation.fields||[]).filter(field=>!field.visible_when||turn.confirmationSelections?.[field.visible_when.field]===field.visible_when.equals);
    const unresolved=visibleFields.filter(field=>!field.value&&(field.required!==false||field.input_type==="date"));
    const intro=node("div","confirmation-intro");
    intro.append(node("strong","","请确认查询条件"),node("span","confirmation-count",unresolved.length?`还需确认 ${unresolved.length} 项`:"条件已完整"));
    box.append(intro);
    const original=node("p","confirmation-original");original.append(node("span","","原问题"),document.createTextNode(confirmation.original_question||turn.question));box.append(original);
    box.append(node("p","confirmation-summary",confirmation.summary||"请确认分析条件。"));
    const fields=node("div","confirmation-fields");
    visibleFields.forEach(field=>{
      const row=node("div",`confirmation-field field-${field.state}`);
      const head=node("span","confirmation-label"); head.append(node("strong","",field.label),node("em",`state-${field.state}`,confirmationStateLabels[field.state]||"暂未提供")); row.append(head);
      if(field.value){ row.append(node("span","confirmed-value",field.value.label||field.value.id)); }
      else if(field.input_type==="date"){
        const input=node("input","confirmation-select");input.type="date";input.dataset.confirmField=field.key;input.dataset.turnIndex=String(index);input.value=turn.confirmationSelections?.[field.key]||"";row.append(input);
      } else {
        const options=node("div","confirmation-options");
        (field.options||[]).forEach(option=>{const item=node("label","confirmation-option");const input=document.createElement("input");input.type="radio";input.name=`confirmation-${index}-${field.key}`;input.value=option.id;input.dataset.confirmField=field.key;input.dataset.turnIndex=String(index);input.checked=turn.confirmationSelections?.[field.key]===option.id;item.append(input,node("span","",option.label));options.append(item);});
        if(!(field.options||[]).length)options.append(node("span","confirmation-empty","暂无可用候选"));
        row.append(options);
      }
      fields.append(row);
    });
    box.append(fields);
    const actions=node("div","confirmation-actions");
    const confirm=node("button","primary confirmation-submit","确认并查询");confirm.type="button";confirm.dataset.confirmTurn=String(index);
    const required=visibleFields.filter(field=>!field.value&&(field.required!==false||field.input_type==="date"));
    confirm.disabled=required.some(field=>!turn.confirmationSelections?.[field.key]);
    const edit=node("button","ghost confirmation-edit","修改问题");edit.type="button";edit.dataset.editTurn=String(index);
    actions.append(confirm,edit);box.append(actions);
    return box;
  }

  function renderAnswer(turn, index) {
    const row = node("article", "message assistant"); row.append(node("span", "bot-avatar", "AI"));
    const card = node("div", `answer-card${state.selectedTurn === index ? " selected" : ""}`); card.dataset.turnIndex = String(index); card.tabIndex=0;
    const top = node("div", "answer-top"); top.append(node("strong", "", "AI 分析助手"));
    if (turn.pending) { top.append(node("span", "result-chip", "查询中")); top.append(node("small", "", "正在连接真实服务")); card.append(top); const body=node("div","answer-body"); body.append(node("p","answer-summary","正在理解问题并查询数据……")); card.append(body); row.append(card); return row; }
    const payload = turn.payload || {}; const view = buildView(payload); const waiting=payload.error?.code==="CLARIFICATION_REQUIRED"&&payload.confirmation; top.append(node("span", "result-chip", waiting?(Object.keys(turn.confirmationSelections||{}).length?"选择中":"待确认"):(payload.error ? "未完成" : view.resultType))); top.append(node("small", "", `${Number(turn.elapsedMs || 0)} ms`)); card.append(top);
    const body = node("div", "answer-body");
    if(waiting){ body.append(renderConfirmation(turn,index,payload)); }
    else if (payload.error) {
      const spec = state.contract.error_states[payload.error.code] || ["查询失败", "查询未完成，请稍后重试。"]; const error = node("div", "error-card"); error.append(node("strong", "", spec[0])); error.append(node("span", "", payload.error.message || spec[1])); body.append(error);
      if (isAuthenticationError(null, payload)) {
        const retry = node("button", "ghost auth-retry", "重新发送");
        retry.type = "button";
        retry.dataset.authRetryTurn = String(index);
        body.append(retry);
      }
    } else {
      if(payload.confirmation?.status==="confirmed") { const final=node("section","final-conditions");final.append(node("strong","","最终采用条件"),node("span","",finalConditionsText(payload.confirmation)));body.append(final); }
      if (view.structured?.headline) body.append(node("h3", "answer-headline", view.structured.headline));
      body.append(node("p", "answer-summary", view.summary));
      const chart = makeChart(view);
      const chartFirst = (
        view.structured?.answerType === "trend"
      );
      if (chartFirst && chart) {
        body.append(chart);
      }
      if (view.structured?.keyMetrics.length) {
        const grid=node("div","kpi-grid");
        view.structured.keyMetrics.forEach(metric=>{const item=node("div","kpi");item.append(node("span","",metric.label||"指标值"));item.append(node("strong","",adapter.answerMetricText(metric)));grid.append(item);});
        body.append(grid);
      } else if (view.resultType === "单值") { const single=adapter.singleValue(view.model); if(single){ const grid=node("div","kpi-grid"); const item=node("div","kpi"); item.append(node("span","",single.metricName)); item.append(node("strong","",single.valueText)); grid.append(item); body.append(grid); } }
      if (view.structured) {
        if (view.rows.length) body.append(makeTable(view));
        if (chart && !chartFirst) body.append(chart);
        if (!view.rows.length && !chart) body.append(node("p", "", "本次查询没有返回数据明细。"));
      } else {
        if (chart) body.append(chart);
        if (view.rows.length) body.append(makeTable(view)); else body.append(node("p", "", "本次查询没有返回数据明细。"));
      }
      body.append(makeResultActions(turn, view, index));
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
    const payload=turn.payload||{}, view=buildView(payload), metadata=payload.metadata||{}, semantic=metadata.semantic||{}, security=metadata.security||{}, confirmation=payload.confirmation||{};
    $("#detail-status").textContent=payload.error?"未完成":"已返回";
    const overview=node("section","detail-group"); overview.append(node("h3","","本轮概览")); kv(overview,"查询耗时",metadata.query_duration_ms==null?"暂未提供":`${metadata.query_duration_ms} ms`); kv(overview,"完整响应",`${Number(turn.elapsedMs||0)} ms`); kv(overview,"结果类型",view.resultType); kv(overview,"推荐图表",view.chart==="none"?"无需图表":view.chart); kv(overview,"请求编号",payload.request_id); root.append(overview);
    const understanding=node("section","detail-group"); understanding.append(node("h3","","系统理解")); kv(understanding,"指标",semantic.metrics); kv(understanding,"机构",semantic.filters?.institution || semantic.filters?.institution_id || semantic.institutions); kv(understanding,"时间",semantic.time_range); kv(understanding,"比较方式",semantic.comparison); root.append(understanding);
    if(confirmation.status){const confirmed=node("section","detail-group");confirmed.append(node("h3","",confirmation.status==="confirmed"?"最终采用条件":"等待用户确认"));kv(confirmed,"确认状态",confirmation.status==="confirmed"?"已确认":"待确认");kv(confirmed,"条件",confirmation.status==="confirmed"?finalConditionsText(confirmation):(confirmation.fields||[]).map(field=>`${field.label}：${confirmationStateLabels[field.state]||field.state}`).join("；"));root.append(confirmed);}
    const source=node("section","detail-group"); source.append(node("h3","","数据与执行")); kv(source,"数据来源",metadata.data_source || metadata.executor); kv(source,"执行路径",metadata.query_path || metadata.generator_mode); root.append(source);
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

  function formatAlertTime(value) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) return "时间未知";
    return date.toLocaleString("zh-CN");
  }

  function renderSecurityCenter() {
    const status = $("#security-status");
    const content = $("#security-content");
    const refresh = $("#refresh-security-alerts");
    if (!status || !content || !refresh) return;
    const loading = state.securityStatus === "loading";
    refresh.disabled = loading;
    refresh.textContent = loading ? "正在刷新…" : "刷新告警";
    content.replaceChildren();

    if (state.securityStatus === "idle") {
      status.textContent = state.fixtureMode ? "验收模式不会访问安全告警接口。" : "尚未加载安全告警。";
      return;
    }
    if (loading) {
      status.textContent = "正在加载安全告警…";
      return;
    }
    if (["authentication_required", "forbidden", "network_error", "invalid_response", "error"].includes(state.securityStatus)) {
      status.textContent = "安全告警加载未完成。";
      const error = node("div", "security-error");
      error.setAttribute("role", "alert");
      error.append(node("strong", "", state.securityStatus === "forbidden" ? "无权访问" : "加载失败"));
      error.append(node("span", "", state.securityError || "请稍后手动刷新。"));
      content.append(error);
      return;
    }

    const counts = securityAlertCounts(state.securityAlerts);
    status.textContent = `已加载 ${counts.total} 条安全告警。`;
    const overview = node("div", "security-overview");
    [["告警总数", counts.total], ["中风险", counts.medium], ["高风险", counts.high], ["严重风险", counts.critical]].forEach(([label, value]) => {
      const card = node("article", "security-kpi");
      card.append(node("span", "", label), node("strong", "", value));
      overview.append(card);
    });
    content.append(overview);

    if (!state.securityAlerts.length) {
      content.append(node("div", "security-empty", "当前没有安全告警。"));
      return;
    }

    const wrap = node("div", "security-table-wrap");
    const table = node("table", "security-table");
    const head = node("thead");
    const headRow = node("tr");
    ["发生时间", "风险等级", "告警类型", "触发次数", "统计窗口", "触发事件", "错误代码", "主体指纹", "请求编号"].forEach(label => headRow.append(node("th", "", label)));
    head.append(headRow);
    table.append(head);
    const body = node("tbody");
    state.securityAlerts.forEach(alert => {
      const row = node("tr");
      const occurred = node("time", "", formatAlertTime(alert.occurredAt));
      occurred.title = alert.occurredAt || "未提供原始时间";
      const severity = node("span", `security-severity severity-${alert.severity || "unknown"}`, securitySeverityLabel(alert.severity));
      const values = [
        occurred,
        severity,
        securityAlertTypeLabel(alert.alertType),
        alert.eventCount,
        formatAlertWindow(alert.windowSeconds),
        alert.triggerEventType || "暂未提供",
        alert.triggerErrorCode || "无",
        alert.actorFingerprint || "暂未提供",
        alert.requestId || "暂未提供",
      ];
      values.forEach(value => {
        const cell = node("td");
        cell.append(value instanceof Node ? value : document.createTextNode(String(value)));
        row.append(cell);
      });
      body.append(row);
    });
    table.append(body);
    wrap.append(table);
    content.append(wrap);
  }

  async function loadSecurityAlerts() {
    if (state.securityStatus === "loading" || state.fixtureMode) return;
    state.securityAlerts = [];
    state.securityRequestId = null;
    state.securityStatus = "loading";
    state.securityError = null;
    renderSecurityCenter();
    try {
      const response = await apiFetch("/api/v1/security/alerts?limit=50", { method: "GET" });
      let payload = {};
      let payloadParsed = true;
      try { payload = await response.json(); }
      catch (_) { payloadParsed = false; }

      payload = applyAuthenticationResponse(response.status, payload);
      const access = securityAlertAccessPolicy(response.status, payload);
      if (access.status !== "success") {
        state.securityStatus = access.status;
        state.securityError = access.message;
        renderSecurityCenter();
        return;
      }
      if (!payloadParsed) {
        state.securityStatus = "invalid_response";
        state.securityError = "服务返回了无法识别的告警数据。";
        renderSecurityCenter();
        return;
      }
      const normalized = normalizeSecurityAlertResponse(payload);
      if (!normalized) {
        state.securityStatus = "invalid_response";
        state.securityError = "服务返回了无法识别的告警数据。";
        renderSecurityCenter();
        return;
      }
      state.securityAlerts = normalized.alerts;
      state.securityRequestId = normalized.requestId;
      state.securityStatus = "success";
      state.securityError = null;
    } catch (_) {
      state.securityStatus = "network_error";
      state.securityError = "无法连接安全告警服务，请稍后手动刷新。";
    }
    renderSecurityCenter();
  }

  function setPage(page, focusHeading = false) {
    state.page=page; document.querySelectorAll("[data-page]").forEach(button=>button.classList.toggle("active",button.dataset.page===page));
    document.querySelector(".workbench").classList.toggle("dashboard-mode",page!=="chat");
    $("#chat-view").hidden=page!=="chat"; $("#dashboard-view").hidden=page!=="dashboard"; $("#security-view").hidden=page!=="security"; $("#detail-content").parentElement.hidden=page!=="chat";
    const titles = { dashboard: ["数据看板", "当前浏览器的真实使用统计"], security: ["安全中心", "受控访问近期安全告警"] };
    const copy = titles[page] || [activeConversation()?.title||"新会话", "用自然语言查询银行经营数据"];
    $("#page-title").textContent=copy[0]; $("#page-subtitle").textContent=copy[1]; $("#head-new-chat").hidden=page!=="chat"; $("#open-details").hidden=page!=="chat";
    closeDrawers();
    if(page==="dashboard")renderDashboard();
    if(state.page === "security") {
      renderSecurityCenter();
      if(state.securityStatus === "idle" && !state.fixtureMode) loadSecurityAlerts();
    }
    if (focusHeading) requestAnimationFrame(() => $("#page-title")?.focus());
  }

  function render() { renderHistory(); renderMessages(); renderDetails(); setPage(state.page); }

  async function submitQuestion(question) {
    const text=question.trim(); if(text.length<2||state.busy)return;
    let conversation=activeConversation(); if(!conversation) conversation=createConversation(text.slice(0,36)); if(!conversation.turns.length) conversation.title=text.slice(0,36);
    const turn={question:text,pending:true,createdAt:new Date().toISOString(),elapsedMs:0,payload:null}; conversation.turns.push(turn); conversation.updatedAt=turn.createdAt; state.selectedTurn=conversation.turns.length-1; state.busy=true; persist(); render(); $("#send").disabled=true;
    const started=performance.now();
    try {
      const response=await apiFetch("/api/v1/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(buildQueryBody(text,conversation.id))});
      let payload; try { payload=await response.json(); } catch(_){ payload={error:{code:"INVALID_RESPONSE",message:"服务返回了无法识别的内容。",retryable:true},columns:[],rows:[]}; }
      payload=applyAuthenticationResponse(response.status,payload);
      if(!response.ok&&!payload.error) payload.error={code:`HTTP_${response.status}`,message:"查询服务暂时未完成请求。",retryable:response.status>=500};
      turn.payload=payload;
    } catch (_) { turn.payload={question:text,columns:[],rows:[],warnings:[],error:{code:"NETWORK_ERROR",message:"无法连接言出数行服务，请确认后端已经启动。",retryable:true},metadata:null}; }
    turn.elapsedMs=Math.max(1,Math.round(performance.now()-started)); turn.pending=false; conversation.updatedAt=new Date().toISOString(); state.busy=false; persist(); $("#send").disabled=false; render();
  }

  async function confirmTurn(index) {
    const conversation=activeConversation(),turn=conversation?.turns?.[index],confirmation=turn?.payload?.confirmation;
    if(!turn||!confirmation||state.busy)return;
    const selections={...(turn.confirmationSelections||{})};
    turn.confirmationEvents=[...(turn.confirmationEvents||[]),{createdAt:new Date().toISOString(),selections}];
    turn.pending=true;state.busy=true;state.selectedTurn=index;persist();render();$("#send").disabled=true;
    const started=performance.now();
    try{
      const response=await apiFetch("/api/v1/query",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(buildQueryBody(turn.question,conversation.id,{token:confirmation.token,selections}))});
      let payload;try{payload=await response.json();}catch(_){payload={error:{code:"INVALID_RESPONSE",message:"服务返回了无法识别的内容。",retryable:true},columns:[],rows:[]};}
      payload=applyAuthenticationResponse(response.status,payload);
      if(!response.ok&&!payload.error)payload.error={code:`HTTP_${response.status}`,message:"查询服务暂时未完成请求。",retryable:response.status>=500};
      turn.payload=payload;
    }catch(_){turn.payload={question:turn.question,columns:[],rows:[],warnings:[],error:{code:"NETWORK_ERROR",message:"无法连接言出数行服务，请确认后端已经启动。",retryable:true},metadata:null,confirmation};}
    turn.elapsedMs=Math.max(1,Math.round(performance.now()-started));turn.pending=false;conversation.updatedAt=new Date().toISOString();state.busy=false;persist();$("#send").disabled=false;render();
  }

  function installFixture() {
    const params=new URLSearchParams(location.search); const fixture=params.get("fixture"); if(!fixture)return;
    state.fixtureMode = true;
    const badge=node("div","fixture-banner",`截图验收模式 · ${fixture} · 数值为明确标注的界面 fixture，不是银行真实数据`); document.body.append(badge);
    const now=new Date().toISOString();
    const fixtures={
      empty:null,
      trend:{question:"演示：最近七天指标趋势",summary:"验收 fixture：指标总体呈上升趋势，仅用于检查图表排版。",columns:["data_date","metric_value"],rows:[["07-20",82],["07-21",91],["07-22",88],["07-23",104],["07-24",110],["07-25",106],["07-26",121]],sql:"SELECT demo_date, demo_value FROM screenshot_fixture",warnings:["验收 fixture，不代表真实业务结果"],error:null,request_id:"fixture_trend",metadata:{result_type:"趋势",chart_type:"line",data_source:"验收 fixture",semantic:{metrics:["演示指标"],time_range:{start:"07-20",end:"07-26"}},security:{audit:"不适用（fixture）"}}},
      history:{question:"演示：本月指标是多少？",summary:"验收 fixture：本月演示值为 121，仅用于检查历史会话恢复。",columns:["data_date","metric_value"],rows:[["本月",121]],sql:"SELECT demo_month, demo_value FROM screenshot_fixture",warnings:["验收 fixture，不代表真实业务结果"],error:null,request_id:"fixture_history_2",metadata:{result_type:"单值",data_source:"验收 fixture",semantic:{metrics:["演示指标"],time_range:{label:"本月"}},security:{audit:"不适用（fixture）"}}}
    };
    if(fixture==="empty"){state.conversations=[];state.activeId=null;state.selectedTurn=null;return;}
    const payload=fixtures[fixture]||fixtures.trend; const turns=fixture==="history"?[{question:fixtures.trend.question,payload:fixtures.trend,elapsedMs:128,createdAt:now,pending:false},{question:payload.question,payload,elapsedMs:96,createdAt:now,pending:false}]:[{question:payload.question,payload,elapsedMs:128,createdAt:now,pending:false}]; state.conversations=[{id:"fixture_conversation",title:fixture==="history"?"验收 fixture：已恢复会话":"验收 fixture：趋势图",createdAt:now,updatedAt:now,turns}]; state.activeId="fixture_conversation"; state.selectedTurn=turns.length-1; if(params.get("page")==="dashboard")state.page="dashboard";
  }

  function bind() {
    $("#new-chat").addEventListener("click",()=>createConversation()); $("#head-new-chat").addEventListener("click",()=>createConversation());
    $("#history-search").addEventListener("input",renderHistory);
    $("#history-list").addEventListener("click",event=>{const target=event.target.closest("[data-conversation-id]");if(!target)return;state.activeId=target.dataset.conversationId;const conversation=activeConversation();state.selectedTurn=conversation?.turns?.length?conversation.turns.length-1:null;state.page="chat";persist();closeDrawers();render();});
    document.querySelector("nav").addEventListener("click",event=>{const target=event.target.closest("[data-page]");if(target)setPage(target.dataset.page,true);});
    $("#message-scroll").addEventListener("change",event=>{const select=event.target.closest("[data-confirm-field]");if(!select)return;const conversation=activeConversation(),turn=conversation?.turns?.[Number(select.dataset.turnIndex)];if(!turn)return;turn.confirmationSelections={...(turn.confirmationSelections||{})};if(select.value)turn.confirmationSelections[select.dataset.confirmField]=select.value;else delete turn.confirmationSelections[select.dataset.confirmField];persist();renderMessages();renderDetails();});
    $("#message-scroll").addEventListener("click",event=>{const authRetry=event.target.closest("[data-auth-retry-turn]");if(authRetry){const turn=activeConversation()?.turns?.[Number(authRetry.dataset.authRetryTurn)];if(turn)submitQuestion(turn.question);return;}const copy=event.target.closest("[data-copy-turn]");if(copy){copyAnalysis(Number(copy.dataset.copyTurn));return;}const download=event.target.closest("[data-export-turn]");if(download){exportCurrentTable(Number(download.dataset.exportTurn));return;}const confirm=event.target.closest("[data-confirm-turn]");if(confirm){confirmTurn(Number(confirm.dataset.confirmTurn));return;}const edit=event.target.closest("[data-edit-turn]");if(edit){const turn=activeConversation()?.turns?.[Number(edit.dataset.editTurn)];if(turn){$("#question").value=turn.question;$("#question").focus();}return;}const suggestion=event.target.closest("[data-question]");if(suggestion){$("#question").value=suggestion.dataset.question;submitQuestion(suggestion.dataset.question);return;}if(event.target.closest("[data-confirm-field],.confirmation-option"))return;const answer=event.target.closest("[data-turn-index]");if(answer){state.selectedTurn=Number(answer.dataset.turnIndex);renderMessages();renderDetails();}});
    $("#composer").addEventListener("submit",event=>{event.preventDefault();const field=$("#question");const question=field.value;field.value="";submitQuestion(question);});
    $("#question").addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();$("#composer").requestSubmit();}});
    $("#open-conversations").addEventListener("click",event=>openDrawer("conversation",event.currentTarget));
    $("#open-details").addEventListener("click",event=>openDrawer("detail",event.currentTarget));
    document.querySelectorAll("[data-close-drawer]").forEach(button=>button.addEventListener("click",()=>closeDrawers()));
    $("#drawer-scrim").addEventListener("click",()=>closeDrawers());
    document.addEventListener("keydown",handleDrawerKeydown);
    window.matchMedia(DESKTOP_DRAWER_QUERY).addEventListener("change",handleDrawerBreakpointChange);
    $("#open-auth").addEventListener("click",event=>openAuthDialog("",event.currentTarget));
    $("#auth-close").addEventListener("click",()=>$("#auth-dialog").close());
    $("#auth-cancel").addEventListener("click",()=>$("#auth-dialog").close());
    $("#auth-logout").addEventListener("click",logoutAuthSession);
    $("#auth-form").addEventListener("submit",async event=>{
      event.preventDefault();
      const input=$("#auth-token"),connect=$("#auth-connect"),message=$("#auth-message");
      connect.disabled=true;
      message.textContent="正在验证访问凭证……";

      const stored=setSessionToken(input.value);
      input.value="";

      if(!stored){
        message.textContent="请输入有效的访问凭证。";
        connect.disabled=false;
        input.focus();
        return;
      }

      const profile=await loadSessionProfile();

      if(!profile){
        clearSessionToken();
        resetSessionProfile();
        updateAuthStatus();
        message.textContent=state.sessionError||"访问凭证无效或已经失效。";
        connect.disabled=false;
        input.focus();
        return;
      }

      message.textContent="";
      connect.disabled=false;
      $("#auth-dialog").close();
      showToast(`${profile.displayName} 已连接`);
    });
    $("#auth-dialog").addEventListener("close",()=>{
      $("#auth-token").value="";
      $("#auth-connect").disabled=false;
      if(authDialogReturnFocus&&typeof authDialogReturnFocus.focus==="function"&&!authDialogReturnFocus.inert)authDialogReturnFocus.focus();
      authDialogReturnFocus=null;
    });
    $("#refresh-security-alerts").addEventListener("click",loadSecurityAlerts);
    syncDrawerAccessibility();
    updateAuthStatus();
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register(
      "/candidate/service-worker.js",
      { scope: "/candidate" },
    ).catch(() => {});
  }

  async function initialize() {
    const response=await fetch("/candidate/assets/result_contract.json"); state.contract=await response.json();
    try { const examples=await fetch("/api/v1/examples"); const payload=await examples.json(); state.suggestions=(payload.examples||[]).map(item=>item.question).filter(Boolean); } catch (_) { state.suggestions=[]; }
    loadConversations(); installFixture(); bind(); render(); registerServiceWorker();
    if(getSessionToken()) await loadSessionProfile();
    const params=new URLSearchParams(location.search);
    const demoMode=params.get("real_demo");
    const demoIndex={single:0,ranking:1,trend:2,"1":1}[demoMode];
    if(Number.isInteger(demoIndex)&&!params.get("fixture")&&state.suggestions[demoIndex]){
      const demoNames={single:"单值",ranking:"机构排名",trend:"趋势"};
      createConversation(`真实数据库联调：${demoNames[demoMode]||"机构排名"}`);
      await submitQuestion(state.suggestions[demoIndex]);
    }
    const intentDemo=params.get("intent_demo");
    if(intentDemo&&!params.get("fixture")){
      createConversation("真实意图确认：存款增长排名");
      await submitQuestion("哪家银行存款增长最好？");
      const conversation=activeConversation(),turn=conversation?.turns?.[0];
      if(turn&&intentDemo==="selecting"){turn.confirmationSelections={growth_method:"custom_range",custom_start_date:"2025-01-01",custom_end_date:"2026-04-30"};persist();render();}
      if(turn&&intentDemo==="confirmed"){turn.confirmationSelections={growth_method:"year_over_year"};persist();render();}
      if(turn&&intentDemo==="confirmed")await confirmTurn(0);
    }
  }
  if (typeof document !== "undefined") initialize().catch(()=>{document.body.replaceChildren(node("div","error-card","候选前端资源加载失败，请重新启动服务。"));});
})();
