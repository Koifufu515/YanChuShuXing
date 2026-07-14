# Sprint 4.3 查询链路可解释性与交易语义

> 历史说明：本文记录 Sprint 4.3 当时的回退 Metadata。自 Sprint 5.2 起，Hybrid 已改为 **Rule First、LLM Extension**，新增 `rule_matched`、`route`、`failure_reason`，旧 `fallback` 仅为兼容保留。

## 实施目标

本阶段只关闭两个缺口：让用户看清一次查询实际由 Rule、LLM 还是 Hybrid 回退完成；补齐交易汇总语义，使第三个演示问题能够由真实 DeepSeek 完成。未增加业务问题、数据库表、RAG、Agent、图表或新的 Pipeline 职责。

## Metadata 设计

`POST /api/v1/query` 请求结构不变，成功响应新增可选 `metadata`：

```json
{
  "configured_mode": "hybrid",
  "executed_generator": "llm",
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "llm_latency_ms": 4153.15,
  "semantic": {
    "intent": "monthly_transaction_summary",
    "business_domain": "transaction",
    "metrics": [
      "transaction_count",
      "transaction_inflow",
      "transaction_outflow",
      "net_transaction_flow"
    ],
    "dimensions": [],
    "filters": {"customer_id": "C001"},
    "time_range": {"start": "2026-06-01", "end": "2026-06-30"},
    "confidence": 0.95
  },
  "fallback": {
    "used": false,
    "reason": null,
    "fallback_generator": null
  }
}
```

`configured_mode` 表示系统配置，例如 Hybrid；`executed_generator` 表示本次真正产生 SQL 的组件。Hybrid 正常使用模型时是 `hybrid / llm`，回退时是 `hybrid / rule`。旧客户端忽略 Metadata 仍可正常读取原字段。

Metadata 在 Generator 内产生，通过框架无关的 `GeneratedSQL` 和 `QueryOutcome` 透传。API 路由不判断模式，Pipeline 只把生成结果携带的 Metadata 放入结果，不读取环境变量或模型配置。

## 回退分类

系统记录稳定代码：`LLM_TIMEOUT`、`LLM_UNAVAILABLE`、`INVALID_SEMANTIC_OUTPUT`、`INVALID_SQL_OUTPUT`、`CLARIFICATION_REQUIRED`、`UNSUPPORTED_METRIC` 和 `CONFIGURATION_ERROR`。前端将常见代码转换为中文说明，但 API 不返回 Prompt、API Key、原始模型响应、请求头或异常堆栈。

## 交易指标口径

四项指标均来自 `transaction_detail`，客户筛选字段为 `customer_id`，时间字段为 `transaction_time`，金额字段为 `amount`，仅统计 `transaction_status = 'SUCCESS'`：

| 指标 | 口径 |
|---|---|
| `transaction_count` | 指定期间成功交易笔数 |
| `transaction_inflow` | 成功且 `direction = 'IN'` 的金额合计 |
| `transaction_outflow` | 成功且 `direction = 'OUT'` 的金额合计 |
| `net_transaction_flow` | 流入金额减流出金额 |

交易 Resolver 会同时召回四项 Metric Context 和真实 Schema 字段。模型生成的结果列继续遵守 `customer_id`、`transaction_count`、`total_in`、`total_out`、`net_amount`，因此确定性 Formatter 无需改成自由文本生成。

## 网页技术详情

业务解释下方新增默认折叠的“技术详情”，展示配置模式、实际 Generator、Provider、模型、语义意图、业务领域、指标、筛选、时间范围、置信度、LLM耗时和回退状态。Metadata 缺失或字段为空时显示空占位，不影响旧响应和错误恢复。

页面继续在 Streamlit 导入前设置 Arrow 系统内存池，结果表格仍使用HTML安全转义，不调用 `st.dataframe`；Session State只保存字典、列表和标量。页面截图：`docs/assets/bankinsight-sprint4-3-explainability.png`。

## 真实 DeepSeek 验证

2026-07-13 使用项目本地 `.env` 和 `deepseek-v4-flash` 完成真实三问：

| 问题 | 实际执行 | 结果 | 回退 |
|---|---|---|---|
| 有效客户数量 | LLM | 2户 | 否 |
| C001账户余额 | LLM | 600万元 | 否 |
| C001 2026年6月交易汇总 | LLM | 3笔，流入10万、流出5万、净流入5万 | 否 |

第三问复验得到 `intent=monthly_transaction_summary`、`business_domain=transaction`、四项交易指标和95%置信度；生成SQL使用命名参数和半开时间区间，Safety允许表仅为 `transaction_detail`。

## 测试与稳定性

- 全量自动化：75项通过。
- `pip check`：通过。
- Python编译：通过。
- API稳定性脚本：60/60通过。
- 真实浏览器：20次双问题交替与30次三问题循环通过，每次核对新Request ID与对应结果。
- 不支持问题后继续正常查询：通过。
- Hybrid超时后继续查询：自动化测试通过。
- 修复后新增 macOS Python Crash Report：0。

## 当前限制

1. 目前只对三个演示问题建立了可靠语义和规则兜底，不代表开放域银行问数准确率。
2. 模型意图、置信度来自结构化模型输出，不是经过统计校准的概率。
3. Rule模式没有模型语义，技术详情只展示最小 Metadata。
4. Metadata 当前用于可解释展示，尚未持久化到审计数据库。
5. HTML结果表格适合小规模 Demo，后续大结果集仍需分页方案。

## 下一步建议

不要立即增加功能。下一步先从竞赛评委视角评审项目的业务价值、差异化、可信度证据、演示节奏和可量化评测，再决定 Sprint 4.4 是否投入评测集、指标覆盖或部署交付。
