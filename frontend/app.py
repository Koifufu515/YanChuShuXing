from __future__ import annotations

import html
import inspect
import json
import os
from pathlib import Path

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

import streamlit as st

from frontend.api_client import APIConnectionError, BankInsightClient
from frontend.kpi_repository import load_overview_metrics


APP_VERSION = "言出数行 0.5.2"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_BASE_URL = os.getenv("BANKINSIGHT_API_URL", "http://127.0.0.1:8000")
DATABASE_PATH = Path(
    os.getenv(
        "BANKINSIGHT_DB_PATH",
        PROJECT_ROOT / "data" / "processed" / "bankinsight.db",
    )
)


def _button_width_kwargs() -> dict[str, object]:
    if "width" in inspect.signature(st.button).parameters:
        return {"width": "stretch"}
    return {"use_container_width": True}


BUSINESS_MODULES = (
    "客户分析",
    "存款分析",
    "贷款分析",
    "理财分析",
    "风险监测",
    "经营分析",
)
SCENARIOS = {
    "客户分析": {
        "icon": ":material/group:",
        "description": "围绕客户规模、活跃度、价值和画像进行分析。",
        "placeholder": "请输入客户分析问题，例如：统计当前有效客户数量",
        "available": True,
        "questions": (
            "统计当前有效客户数量。",
            "查询客户 C001 当前账户余额。",
            "统计客户 C001 在 2026 年 6 月交易汇总。",
            "近三个月交易最活跃的客户是谁？",
            "账户余额最高的五位客户。",
            "六月净流入最高的客户是谁？",
        ),
    },
    "存款分析": {
        "icon": ":material/account_balance_wallet:",
        "description": "围绕存款规模、结构、变化趋势和客户贡献进行分析。",
        "placeholder": "请输入存款分析问题，例如：本月各分行存款余额如何变化",
        "available": False,
        "questions": (
            "本月各分行存款余额排名如何？",
            "近三个月存款余额增长趋势如何？",
            "定期与活期存款结构占比是多少？",
            "存款余额增长最快的客户群体是谁？",
            "本月新增存款客户有多少？",
            "哪些分行存款余额出现下降？",
        ),
    },
    "贷款分析": {
        "icon": ":material/account_balance:",
        "description": "围绕贷款投放、余额、结构和资产质量进行分析。",
        "placeholder": "请输入贷款分析问题，例如：近三个月各分行贷款余额变化",
        "available": False,
        "questions": (
            "近三个月各分行贷款余额如何变化？",
            "本月新增贷款金额是多少？",
            "贷款余额最高的五家分行是谁？",
            "不同客户类型的贷款结构如何？",
            "本季度贷款投放完成率是多少？",
            "哪些分行贷款余额连续下降？",
        ),
    },
    "理财分析": {
        "icon": ":material/trending_up:",
        "description": "围绕理财销售、产品表现、客户转化和资产配置进行分析。",
        "placeholder": "请输入理财分析问题，例如：本月理财产品销售额排名",
        "available": False,
        "questions": (
            "本月理财产品销售额排名如何？",
            "理财客户转化率是多少？",
            "近三个月理财购买金额如何变化？",
            "高净值客户最偏好哪些产品？",
            "即将到期的理财金额是多少？",
            "各分行理财销售完成率如何？",
        ),
    },
    "风险监测": {
        "icon": ":material/shield:",
        "description": "围绕逾期、异常交易、风险客户和预警事件进行监测。",
        "placeholder": "请输入风险监测问题，例如：本月贷款逾期率是否异常",
        "available": False,
        "questions": (
            "本月贷款逾期率是否异常？",
            "高风险客户主要分布在哪些地区？",
            "近七天有哪些异常大额交易？",
            "逾期金额最高的客户群体是谁？",
            "哪些分行风险事件增长较快？",
            "本月新增风险预警有多少条？",
        ),
    },
    "经营分析": {
        "icon": ":material/analytics:",
        "description": "汇总核心经营指标，快速识别规模、效率和趋势变化。",
        "placeholder": "请输入经营分析问题，例如：统计当前有效客户数量",
        "available": True,
        "questions": (
            "统计当前有效客户数量。",
            "查询客户 C001 当前账户余额。",
            "统计客户 C001 在 2026 年 6 月交易汇总。",
            "六月净流入最高的客户是谁？",
            "近三个月交易最活跃的客户是谁？",
            "账户余额最高的五位客户。",
        ),
    },
}
QUESTION_NORMALIZATION = {
    "统计当前有效客户数量。": "查询有效客户数量",
    "查询客户 C001 当前账户余额。": "查询客户C001的账户余额",
    "统计客户 C001 在 2026 年 6 月交易汇总。": "查询客户C001在2026年6月的交易汇总",
}
FIELD_LABELS = {
    "customer_id": "客户编号",
    "customer_count": "有效客户数",
    "account_balance": "账户余额",
    "transaction_count": "成功交易笔数",
    "total_in": "流入金额",
    "total_out": "流出金额",
    "net_amount": "净流入金额",
}
MODE_LABELS = {"rule": "规则模式", "llm": "大模型模式", "hybrid": "混合模式"}
EXECUTOR_LABELS = {"rule": "规则执行器", "llm": "大模型执行器"}
ROUTE_LABELS = {"Rule": "规则路径", "LLM": "大模型路径"}
PROVIDER_LABELS = {"deepseek": "深度求索"}
MODEL_LABELS = {"deepseek-v4-flash": "深度求索极速版", "deepseek-v4-pro": "深度求索专业版"}
DOMAIN_LABELS = {"customer": "客户分析", "customer_asset": "客户资产", "transaction": "交易分析"}
INTENT_LABELS = {
    "active_customer_count": "有效客户统计",
    "customer_account_balance": "客户账户余额查询",
    "monthly_transaction_summary": "客户月度交易汇总",
    "query_task": "经营数据查询",
}
METRIC_LABELS = {
    "active_customer_count": "有效客户数",
    "deposit_balance": "存款余额",
    "transaction_count": "成功交易笔数",
    "transaction_inflow": "交易流入金额",
    "transaction_outflow": "交易流出金额",
    "net_transaction_flow": "交易净流入",
}
FALLBACK_LABELS = {
    "LLM_TIMEOUT": "大模型请求超时",
    "LLM_UNAVAILABLE": "大模型服务不可用",
    "INVALID_SEMANTIC_OUTPUT": "业务语义输出无效",
    "INVALID_SQL_OUTPUT": "查询语句输出无效",
    "CLARIFICATION_REQUIRED": "查询条件需要补充",
    "UNSUPPORTED_METRIC": "指标尚未定义",
    "CONFIGURATION_ERROR": "模型配置不可用",
}
FAILURE_REASON_LABELS = {
    "missing_parameter": "缺少必要查询条件",
    "unsupported_metric": "指标尚未支持",
    "llm_timeout": "模型服务请求超时",
    "llm_unavailable": "模型服务暂不可用",
    "unsafe_sql": "查询未通过安全校验",
    "invalid_llm_output": "模型输出格式无效",
    "configuration_error": "模型配置不可用",
    "unsupported_question": "问题暂不支持",
    "generation_failed": "查询生成失败",
}


st.set_page_config(
    page_title="言出数行——银行智能问数与协同分析系统",
    page_icon="数",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={},
)


def _apply_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #172033;
            --muted: #667085;
            --blue: #175cd3;
            --blue-dark: #1849a9;
            --blue-soft: #eff6ff;
            --line: #dfe5ec;
            --surface: #ffffff;
            --canvas: #f5f7fa;
            --radius: 6px;
            --shadow: 0 1px 3px rgba(16, 24, 40, .08);
        }
        header[data-testid="stHeader"], [data-testid="stToolbar"],
        [data-testid="stDecoration"], #MainMenu, footer { display: none !important; }
        .stApp { background: var(--canvas); color: var(--ink); }
        .block-container { max-width: 1180px; padding: 2.4rem 2rem 4rem; }
        h1, h2, h3, p, label, button { letter-spacing: 0 !important; }
        h2 { font-size: 1.28rem !important; margin: 2rem 0 .9rem !important; }
        .brand { font-size: 2rem; line-height: 1.15; font-weight: 700; color: var(--ink); }
        .subtitle { color: var(--muted); font-size: 1rem; margin-top: .4rem; }
        .scenario-heading { margin: 1.8rem 0 .75rem; color: var(--muted); font-size: .82rem; font-weight: 650; }
        .st-key-scenario_selector { margin-bottom: .8rem; }
        .st-key-scenario_selector div[data-testid="stButton"] button { min-height: 4.2rem; justify-content: flex-start; padding: .75rem .85rem; background: #f8fafc; border: 1px solid var(--line); box-shadow: none; }
        .st-key-scenario_selector div[data-testid="stButton"] button:hover { border-color: #84adf4; background: #f8fbff; box-shadow: 0 3px 8px rgba(16, 24, 40, .08); transform: translateY(-1px); }
        .st-key-scenario_selector div[data-testid="stButton"] button[kind="primary"] { background: var(--blue); border-color: var(--blue); color: #fff; box-shadow: 0 3px 8px rgba(23, 92, 211, .16); }
        .st-key-scenario_selector div[data-testid="stButton"] button[kind="primary"]:hover { background: var(--blue-dark); border-color: var(--blue-dark); color: #fff; }
        .scenario-description { color: #475467; font-size: .92rem; line-height: 1.6; margin: .4rem 0 1.25rem; }
        .scenario-notice { background: #f8fafc; border: 1px solid #d8e1ec; border-left: 3px solid #84adf4; border-radius: var(--radius); color: #475467; font-size: .88rem; line-height: 1.6; margin: .8rem 0 1rem; padding: .72rem .9rem; }
        .section-label { color: var(--ink); font-size: 1.1rem; font-weight: 650; margin: 1.5rem 0 .75rem; }
        .overview-grid, .query-metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .8rem; }
        .metric-card { min-height: 96px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 1rem 1.1rem; }
        .metric-label { color: var(--muted); font-size: .82rem; margin-bottom: .5rem; }
        .metric-value { color: var(--ink); font-size: 1.55rem; font-weight: 700; line-height: 1.2; overflow-wrap: anywhere; }
        .query-panel { margin: 2rem 0 1.1rem; padding: 1.6rem 0 1.3rem; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
        .query-title { color: var(--ink); font-size: 1.25rem; font-weight: 700; margin-bottom: .3rem; }
        .query-caption { color: var(--muted); font-size: .9rem; margin-bottom: .9rem; }
        div[data-testid="stTextArea"] textarea { background: #fff; border: 1px solid #b9c6d5; border-radius: var(--radius); font-size: 1rem; line-height: 1.6; padding: .9rem 1rem; }
        div[data-testid="stTextArea"] textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(23, 92, 211, .12); }
        div[data-testid="stButton"] button { min-height: 2.65rem; border-radius: var(--radius); border-color: #cdd6e1; color: #344054; font-weight: 600; }
        div[data-testid="stButton"] button:hover { border-color: var(--blue); color: var(--blue-dark); }
        div[data-testid="stButton"] button[kind="primary"] { background: var(--blue); border-color: var(--blue); color: #fff; }
        div[data-testid="stButton"] button[kind="primary"]:hover { background: var(--blue-dark); border-color: var(--blue-dark); color: #fff; }
        .result-band { margin-top: 2.2rem; padding-top: .2rem; }
        .conclusion { background: var(--blue-soft); border-left: 4px solid var(--blue); padding: 1rem 1.2rem; color: #12335b; font-size: 1rem; line-height: 1.7; }
        .result-table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: var(--radius); background: #fff; box-shadow: var(--shadow); }
        .result-table { width: 100%; border-collapse: collapse; min-width: 520px; }
        .result-table th, .result-table td { padding: .75rem .9rem; border-bottom: 1px solid var(--line); text-align: left; overflow-wrap: anywhere; }
        .result-table th { background: #f8fafc; color: #475467; font-size: .82rem; font-weight: 650; }
        .result-table td { color: var(--ink); font-size: .92rem; }
        .result-table tbody tr:last-child td { border-bottom: 0; }
        div[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: var(--radius); background: #fff; box-shadow: none; }
        code { font-size: .84rem !important; }
        @media (max-width: 760px) {
            .block-container { padding: 1.4rem 1rem 3rem; }
            .overview-grid, .query-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .st-key-scenario_selector div[data-testid="stButton"] button { min-height: 3.8rem; }
            .metric-card { min-height: 88px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _select_question(question: str) -> None:
    st.session_state.question = QUESTION_NORMALIZATION.get(question, question)
    st.session_state.pop("api_result", None)


def _select_scenario(scenario: str) -> None:
    st.session_state["selected_scenario"] = scenario
    st.session_state["question"] = ""
    st.session_state.pop("api_result", None)


def _show_scenario_selector(selected: str) -> None:
    st.markdown('<div class="scenario-heading">业务场景</div>', unsafe_allow_html=True)
    with st.container(key="scenario_selector"):
        columns = st.columns(len(BUSINESS_MODULES), gap="small")
        for column, name in zip(columns, BUSINESS_MODULES):
            scenario = SCENARIOS[name]
            column.button(
                name,
                key=f"scenario_{name}",
                icon=scenario["icon"],
                type="primary" if name == selected else "secondary",
                **_button_width_kwargs(),
                on_click=_select_scenario,
                args=(name,),
            )


def _cards_html(items: list[tuple[str, str]], css_class: str) -> str:
    cards = "".join(
        '<div class="metric-card">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(value)}</div>'
        "</div>"
        for label, value in items
    )
    return f'<div class="{css_class}">{cards}</div>'


def _overview_items() -> list[tuple[str, str]]:
    try:
        metrics = load_overview_metrics(DATABASE_PATH)
    except OSError:
        return [
            ("有效客户数", "暂不可用"),
            ("账户数量", "暂不可用"),
            ("交易总数", "暂不可用"),
            ("理财产品数", "暂不可用"),
        ]
    return [(label, f"{value:,}") for label, value in metrics]


def _display_value(column: str, value: object) -> str:
    if column in {"account_balance", "total_in", "total_out", "net_amount"}:
        return f"{float(value or 0) / 10_000:,.2f} 万元"
    if column == "customer_count":
        return f"{int(value or 0):,} 户"
    if column == "transaction_count":
        return f"{int(value or 0):,} 笔"
    return str(value)


def _result_table_html(columns: list[str], rows: list[list]) -> str:
    header = "".join(
        f"<th>{html.escape(FIELD_LABELS.get(column, column))}</th>" for column in columns
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(_display_value(column, value))}</td>"
            for column, value in zip(columns, row)
        )
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="result-table-wrap"><table class="result-table"><thead><tr>'
        f"{header}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _query_metric_items(payload: dict) -> list[tuple[str, str]]:
    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    if not rows:
        return []
    values = dict(zip(columns, rows[0]))
    return [
        (FIELD_LABELS[column], _display_value(column, values[column]))
        for column in (
            "customer_count",
            "account_balance",
            "transaction_count",
            "total_in",
            "total_out",
            "net_amount",
        )
        if column in values
    ]


def _session_result(api_result: object) -> dict:
    return {
        "payload": dict(getattr(api_result, "payload")),
        "elapsed_ms": int(getattr(api_result, "elapsed_ms")),
    }


def _mapped_filter_text(filters: object) -> str:
    if not isinstance(filters, dict) or not filters:
        return "无"
    mapped = {FIELD_LABELS.get(str(key), str(key)): value for key, value in filters.items()}
    return json.dumps(mapped, ensure_ascii=False)


def _time_range_text(time_range: object) -> str:
    if not isinstance(time_range, dict) or not time_range:
        return "无"
    start = time_range.get("start") or time_range.get("start_date")
    end = time_range.get("end") or time_range.get("end_date")
    if start and end:
        return f"{start} 至 {end}"
    return "已指定"


def _technical_detail_rows(
    metadata: object, payload: dict | None = None, elapsed_ms: int | None = None
) -> list[tuple[str, str]]:
    data = metadata if isinstance(metadata, dict) else {}
    semantic = data.get("semantic") if isinstance(data.get("semantic"), dict) else {}
    fallback = data.get("fallback") if isinstance(data.get("fallback"), dict) else {}
    metrics = semantic.get("metrics") if isinstance(semantic.get("metrics"), list) else []
    reason = fallback.get("reason")
    failure_reason = data.get("failure_reason")
    confidence = semantic.get("confidence")
    latency = data.get("llm_latency_ms")
    payload = payload or {}
    return [
        ("运行模式", MODE_LABELS.get(str(data.get("configured_mode")), "未提供")),
        ("实际执行器", EXECUTOR_LABELS.get(str(data.get("executed_generator")), "未提供")),
        ("查询路径", ROUTE_LABELS.get(str(data.get("route")), "未提供")),
        (
            "规则命中",
            "是" if data.get("rule_matched") is True else "否"
            if data.get("rule_matched") is False
            else "未提供",
        ),
        (
            "失败原因",
            FAILURE_REASON_LABELS.get(str(failure_reason), str(failure_reason))
            if failure_reason
            else "无",
        ),
        ("模型提供方", PROVIDER_LABELS.get(str(data.get("provider")), "未使用")),
        ("模型版本", MODEL_LABELS.get(str(data.get("model")), "未使用")),
        ("语义意图", INTENT_LABELS.get(str(semantic.get("intent")), "未提供")),
        ("业务领域", DOMAIN_LABELS.get(str(semantic.get("business_domain")), "未提供")),
        ("识别指标", "、".join(METRIC_LABELS.get(str(item), str(item)) for item in metrics) or "无"),
        ("筛选条件", _mapped_filter_text(semantic.get("filters"))),
        ("时间范围", _time_range_text(semantic.get("time_range"))),
        ("置信度", f"{float(confidence):.2%}" if isinstance(confidence, (int, float)) else "未提供"),
        ("模型耗时", f"{float(latency):.0f} 毫秒" if isinstance(latency, (int, float)) else "未使用"),
        ("回退状态", "已回退" if fallback.get("used") is True else "未回退"),
        ("回退原因", FALLBACK_LABELS.get(str(reason), "无") if reason else "无"),
        ("页面版本", APP_VERSION),
        ("查询耗时", f"{elapsed_ms} 毫秒" if elapsed_ms is not None else "未提供"),
        ("请求编号", str(payload.get("request_id") or "未提供")),
    ]


def _show_technical_details(metadata: object, payload: dict, elapsed_ms: int) -> None:
    with st.expander("技术详情", expanded=False):
        for label, value in _technical_detail_rows(metadata, payload, elapsed_ms):
            st.markdown(f"**{html.escape(label)}：** {html.escape(value)}")


def _show_result(payload: dict, elapsed_ms: int) -> None:
    error = payload.get("error")
    if error:
        message = error.get("message", "查询未完成，请稍后重试。")
        st.error(message)
        _show_technical_details(payload.get("metadata"), payload, elapsed_ms)
        return

    st.markdown('<div class="result-band"></div>', unsafe_allow_html=True)
    st.markdown("## 业务结论")
    summary = payload.get("summary") or "当前结果暂无可用结论。"
    st.markdown(
        f'<div class="conclusion">{html.escape(str(summary))}</div>',
        unsafe_allow_html=True,
    )

    metric_items = _query_metric_items(payload)
    if metric_items:
        st.markdown("## 关键指标")
        st.markdown(
            _cards_html(metric_items, "query-metric-grid"), unsafe_allow_html=True
        )

    st.markdown("## 查询结果")
    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    if columns:
        st.markdown(_result_table_html(columns, rows), unsafe_allow_html=True)
    else:
        st.info("本次查询没有返回数据。")

    for warning in payload.get("warnings") or []:
        st.warning(warning)

    st.markdown("## 生成 SQL")
    st.code(payload.get("sql") or "-- 本次查询未生成 SQL", language="sql")
    _show_technical_details(payload.get("metadata"), payload, elapsed_ms)


def _show_recommended_questions(questions: tuple[str, ...]) -> None:
    st.markdown('<div class="section-label">推荐问题</div>', unsafe_allow_html=True)
    for start in range(0, len(questions), 3):
        columns = st.columns(3)
        for column, question in zip(columns, questions[start : start + 3]):
            column.button(
                question,
                key=f"recommend_{start}_{question}",
                **_button_width_kwargs(),
                on_click=_select_question,
                args=(question,),
            )


def main() -> None:
    _apply_style()
    st.markdown(
        '<div class="brand">言出数行——银行智能问数与协同分析系统</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="subtitle">面向银行经营分析场景的智能问数与协同分析平台</div>',
        unsafe_allow_html=True,
    )
    if "selected_scenario" not in st.session_state:
        st.session_state.selected_scenario = "经营分析"
    selected_scenario = st.session_state.selected_scenario
    scenario = SCENARIOS[selected_scenario]
    _show_scenario_selector(selected_scenario)
    st.markdown(
        f'<div class="scenario-description">{html.escape(scenario["description"])}</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-label">经营概览</div>', unsafe_allow_html=True)
    st.markdown(_cards_html(_overview_items(), "overview-grid"), unsafe_allow_html=True)

    if "question" not in st.session_state:
        st.session_state.question = ""

    st.markdown(
        f'<div class="query-panel"><div class="query-title">{html.escape(selected_scenario)}</div>'
        '<div class="query-caption">用自然语言查询业务指标，系统将自动完成口径匹配、安全校验和结果解释。</div></div>',
        unsafe_allow_html=True,
    )
    if not scenario["available"]:
        st.markdown(
            '<div class="scenario-notice">当前为产品演示版本，该模块已完成产品设计，业务能力将在后续版本中逐步开放。</div>',
            unsafe_allow_html=True,
        )
    st.text_area(
        f"{selected_scenario}问题",
        key="question",
        height=138,
        placeholder=scenario["placeholder"],
        label_visibility="collapsed",
    )
    action_columns = st.columns([3, 1])
    with action_columns[1]:
        start_analysis = st.button(
            "开始分析", type="primary", **_button_width_kwargs()
        )

    _show_recommended_questions(scenario["questions"])

    if start_analysis:
        question = st.session_state.question.strip()
        if not question:
            st.warning("请先输入需要分析的问题。")
        else:
            try:
                with st.spinner("正在理解问题并查询经营数据……"):
                    st.session_state.api_result = _session_result(
                        BankInsightClient(API_BASE_URL).query(question)
                    )
            except APIConnectionError as error:
                st.session_state.api_result = None
                st.error(str(error))

    api_result = st.session_state.get("api_result")
    if api_result is not None:
        _show_result(api_result["payload"], api_result["elapsed_ms"])


if __name__ == "__main__":
    main()
