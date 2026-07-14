# Sprint 4.2 DeepSeek 接入与规则回退

> 历史说明：本文记录 Sprint 4.2 当时的 LLM First 实现。自 Sprint 5.2 起，当前系统已改为 **Rule First、LLM Extension**；LLM 失败后不再回退 Rule。当前行为以根目录 `README.md` 和最新代码为准。

## 实施目标

本阶段在不修改 QueryPipeline 编排职责的前提下，通过现有 `LLMProvider` 和 `SQLGenerator` Ports 接入 DeepSeek。系统支持 `rule`、`llm`、`hybrid` 三种模式；API 请求结构和 Streamlit 查询逻辑保持不变。

## 调用链

```text
QueryPipeline
  -> SQLGenerator Port
      -> rule: RuleSQLGenerator
      -> llm: LLMSQLGenerator
          -> DeepSeekLLMProvider（业务语义 JSON）
          -> DeepSeekLLMProvider（SQL JSON）
      -> hybrid: LLMSQLGenerator -> 失败时 RuleSQLGenerator
  -> 原有 SQLGlot Safety
  -> 原有 Readonly SQLite Executor
  -> 原有 Template Result Formatter
```

Pipeline 不读取 `.env`，不了解 DeepSeek、Prompt、模式或回退。模式选择只发生在 `bootstrap/container.py`。

## 两阶段业务语义解析

第一阶段要求模型返回严格 JSON，包括意图、业务主题、指标、维度、筛选条件、时间范围、排序、限制和是否需要澄清。解析器验证必填字段、字段类型和指标 ID；Markdown 围栏、非法 JSON、未知指标和错误类型均被拒绝，不做猜测性修复。

第二阶段把原始问题、已验证业务语义、Schema Context、Metric Context、允许表、拒绝字段和 SQLite 约束交给模型。模型只能返回 `sql`、`parameters`、`warnings`。Generator 不执行 SQL，也不替代 SQLGlot Safety。

DeepSeek Provider 使用官方 OpenAI-compatible `POST /chat/completions`，启用 JSON Output 和非思考模式。根据2026年7月官方文档，推荐模型为 `deepseek-v4-flash` / `deepseek-v4-pro`；旧 `deepseek-chat` 将于2026-07-24停用。参考：[DeepSeek 首次调用](https://api-docs.deepseek.com/)、[Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion)。

## Prompt 约束

- 只返回一个 JSON 对象，不使用 Markdown 或解释文字；
- 语义字段类型固定，空数组、空对象和 `null` 不混用；
- 指标必须来自当前 Metric Context；
- SQL 只能使用当前 Schema Context 和允许表；
- 只允许一条 SELECT/CTE，动态值优先使用命名参数；
- 禁止写操作、PRAGMA、多语句和虚构字段；
- 生成结果仍必须经过独立 Safety Checker。

## 配置与密钥

`.env.example` 提供以下变量：Generator 模式、Provider、Base URL、API Key、模型、超时和温度。本地 `.env` 由 `Settings` 在 Composition Root 加载，系统环境变量优先。`.gitignore` 明确忽略 `.env`。

`rule` 不需要 LLM 配置；`llm` 缺配置时返回 `CONFIGURATION_ERROR`；`hybrid` 缺配置时对固定问题回退规则并返回 Warning。Provider 的网络、HTTP、超时和响应错误全部转成稳定应用异常，不向前端传递密钥、原始响应体或传输细节。

## Hybrid 回退

Hybrid 仅捕获配置缺失、Provider 超时/不可用、模型输出无效和需要澄清等可预期错误。随后调用原有 Rule Generator；若问题不在三条固定规则内，仍返回 `UNSUPPORTED_QUESTION`，不会映射到无关 SQL。Safety 拒绝发生在 Pipeline，Hybrid 不复制 SQLGlot 逻辑。

## 自动化测试

测试全部使用 Fake Provider，不访问真实 DeepSeek。覆盖合法/非法语义 JSON、澄清、合法/非法 SQL JSON、Markdown、空响应、超时、网络失败、HTTP 错误、Hybrid 成功与回退、未覆盖问题、三模式 API 契约及危险 SQL 被原 Safety 拒绝。Sprint 3、Sprint 4.1 回归测试继续运行。

## 真实 Smoke Test

使用桌面项目本地 `.env`，临时将本次测试超时提高到60秒，完成三个现有问题：

| 问题 | 结果 | LLM/回退 |
|---|---|---|
| 查询有效客户数量 | 2户 | DeepSeek两阶段成功，未回退 |
| 查询客户C001的账户余额 | 600万元 | DeepSeek两阶段成功，未回退 |
| 查询客户C001在2026年6月的交易汇总 | 3笔，流入10万、流出5万、净流入5万 | 当前交易指标上下文不足，Hybrid安全回退规则 |

首次真实调用还发现本机 Python CA 证书链问题，Provider 已通过 `certifi` 显式加载可信 CA。一次20秒请求出现瞬时超时，60秒 Smoke 重试成功；正式演示建议将超时配置为30至60秒。

最终复验中，有效客户数与账户余额的模型总耗时分别约1.85秒和2.25秒，Template Result Formatter 分别生成“当前有效客户数量为2户”和“客户C001当前有效账户余额合计为600.00万元”。第三问明确记录 `fallback_used=true` 和 `UNSUPPORTED_QUESTION`，随后由规则生成器完成查询与解释。全程未输出 API Key。

## 当前限制

1. 外部 v1 响应尚未增加 metadata，因此网页不能逐次展示模型、LLM耗时和回退状态；Smoke Test 可完整观察这些信息。
2. 交易汇总尚无独立 Metric Context，真实 LLM 在该问题上可能要求澄清，Hybrid 会回退。
3. 当前只实现 DeepSeek Adapter，不包含其他厂商、RAG、向量检索、自动修复或多轮会话。
4. 模型输出具有概率性，严格解析和 Safety 会把不可接受输出转为错误或回退，而不是保证每次 LLM 都成功。

## 下一阶段建议

下一阶段优先设计向后兼容的可选 `metadata`，让前端展示生成模式、模型耗时、业务语义和回退状态；随后补齐“交易汇总”指标定义与 Gold SQL 评测集。不要先扩大到更多业务问题，也不要引入 Agent 或 RAG。

## Sprint 4.3 后续状态

上述两个缺口已在 Sprint 4.3 关闭。API 已增加可选 Metadata，Streamlit 已展示技术详情；交易汇总已补齐四项指标语义。2026-07-13 真实复验中，DeepSeek 将第三问识别为 `monthly_transaction_summary / transaction`，生成参数化 SQLite SQL并通过原 Safety，未发生 Rule 回退。完整记录见 `docs/Sprint4_Explainability_and_Transaction_Metrics.md`。
