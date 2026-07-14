# BankInsight Sprint 3 架构实施与最小原型记录

> 日期：2026-07-12
> 目标：按轻量端口与适配器架构完成首个真实纵向闭环
> 结论：规则型原型已运行；未接入真实 LLM 或网页

## 一、实施结果

Sprint 3 已实现以下真实链路：

```text
POST /api/v1/query
  -> QueryRequestDTO
  -> QueryCommand
  -> YAMLContextResolver
  -> RuleSQLGenerator
  -> SQLGlotSafetyChecker
  -> SQLiteExecutor
  -> TemplateResultFormatter
  -> QueryOutcome
  -> QueryResponseDTO
```

FastAPI、SQLite、SQLGlot 和 Pydantic 只出现在对应 Adapter 或 API 层。`application/pipeline.py` 只依赖应用模型、统一异常和 Ports。

## 二、实际创建、迁移和修改的文件

### 新增应用层与 Ports

- `backend/app/application/models.py`
- `backend/app/application/errors.py`
- `backend/app/application/pipeline.py`
- `backend/app/ports/context_resolver.py`
- `backend/app/ports/sql_generator.py`
- `backend/app/ports/llm_provider.py`
- `backend/app/ports/sql_safety.py`
- `backend/app/ports/database_executor.py`
- `backend/app/ports/result_formatter.py`
- `backend/app/ports/audit_logger.py`

### 新增 Adapters 与组装入口

- `backend/app/adapters/context/yaml_resolver.py`
- `backend/app/adapters/generation/rule_generator.py`
- `backend/app/adapters/safety/sqlglot_checker.py`
- `backend/app/adapters/database/init_db.py`
- `backend/app/adapters/database/sqlite_executor.py`
- `backend/app/adapters/formatting/template_formatter.py`
- `backend/app/adapters/audit/noop_logger.py`
- `backend/app/bootstrap/container.py`

### API 与依赖

- 新增 `backend/app/api/schemas.py`
- 新增 `backend/app/api/error_handlers.py`
- 修改 `backend/app/api/query.py`
- 修改 `backend/app/main.py`
- 新增 `backend/requirements-dev.txt`
- 修改 `backend/app/services/pipeline.py` 为兼容导入，不再承载接口与实现

### 数据与测试

- 生成 `data/processed/bankinsight.db`
- 新增 `tests/test_architecture_contracts.py`
- 新增 `tests/test_database_init.py`
- 新增 `tests/test_sqlite_executor.py`
- 新增 `tests/test_rule_sql_generator.py`
- 新增 `tests/test_sql_safety_adapter.py`
- 新增 `tests/test_result_formatter.py`
- 新增 `tests/test_pipeline.py`
- 新增 `tests/test_api.py`

保留且复用了 `sql/schema.sql`、`config/schema.yml`、`config/metrics.yml` 和 `backend/app/core/sql_safety.py`，没有无理由重写。

## 三、最终目录结构

```text
backend/app/
├── api/
│   ├── error_handlers.py
│   ├── query.py
│   └── schemas.py
├── application/
│   ├── errors.py
│   ├── models.py
│   └── pipeline.py
├── ports/
│   ├── audit_logger.py
│   ├── context_resolver.py
│   ├── database_executor.py
│   ├── llm_provider.py
│   ├── result_formatter.py
│   ├── sql_generator.py
│   └── sql_safety.py
├── adapters/
│   ├── audit/noop_logger.py
│   ├── context/yaml_resolver.py
│   ├── database/init_db.py
│   ├── database/sqlite_executor.py
│   ├── formatting/template_formatter.py
│   ├── generation/rule_generator.py
│   └── safety/sqlglot_checker.py
├── bootstrap/container.py
├── core/sql_safety.py
├── services/pipeline.py
└── main.py
```

没有创建微服务、完整 DDD、插件系统、消息队列或空的 LLM 实现文件。

## 四、Pipeline 运行顺序与职责

`QueryPipeline.run` 的顺序固定为：

1. 记录 `request_started`；
2. Context Resolver 返回 `QueryContext`；
3. SQL Generator 返回参数化 `GeneratedSQL`；
4. Safety Checker 返回 `SafetyResult`；
5. 若拒绝，记录 `query_rejected`，不调用数据库；
6. 若允许，Database Executor 只读执行；
7. Result Formatter 生成确定性摘要；
8. 记录 `query_succeeded` 或 `query_failed`；
9. 返回统一 `QueryOutcome`。

Pipeline 不读取 YAML、不写 Prompt、不调用模型 SDK、不打开 SQLite、不解析 AST、不包含固定问题判断、不决定 HTTP 状态码。

## 五、固定问题与真实返回结果

### 5.1 有效客户数量

请求问题：`查询有效客户数量`

```json
{
  "columns": ["customer_count"],
  "rows": [[2]],
  "summary": "当前有效客户数量为2户。",
  "error": null
}
```

### 5.2 客户账户余额

请求问题：`查询客户C001的账户余额`

```json
{
  "columns": ["customer_id", "account_balance"],
  "rows": [["C001", 6000000]],
  "summary": "客户C001当前有效账户余额合计为600.00万元。",
  "error": null
}
```

### 5.3 客户月度交易汇总

请求问题：`查询客户C001在2026年6月的交易汇总`

```json
{
  "columns": ["customer_id", "transaction_count", "total_in", "total_out", "net_amount"],
  "rows": [["C001", 3, 100000, 50000, 50000]],
  "summary": "客户C001在该期间共有3笔成功交易，流入10.00万元，流出5.00万元，净流入5.00万元。",
  "error": null
}
```

上述结果来自 `data/processed/bankinsight.db`，不是测试中硬编码的 API 返回值。

## 六、数据库初始化与安全

初始化器执行现有 `schema.sql`，在临时数据库写入3名客户、4个账户和4笔交易，完成外键检查后原子替换目标数据库。重复执行会重建同一数据，不会重复增长。

SQLite Executor 使用 `mode=ro` 和 `PRAGMA query_only=ON`，支持参数绑定、最多1000行、截断判断、计时、连接自动关闭，并通过 SQLite progress handler 中断超时查询。写操作即使绕过上层 Safety，也会被只读数据库拒绝。

SQLGlot Adapter 复用原有 Validator。自动化测试覆盖 SELECT、CTE、DELETE、多语句、未知表和拒绝字段；Safety 拒绝后 Pipeline 测试证明 Executor 不会被调用。

## 七、错误结构

所有 API 响应固定包含：

```text
request_id, question, sql, columns, rows, summary, warnings, error
```

当前已验证：

| 状态 | 错误码 | 场景 |
|---:|---|---|
| 400 | `UNSUPPORTED_QUESTION` | 规则生成器不支持问题 |
| 403 | `SQL_REJECTED` | SQL 安全拒绝 |
| 422 | `REQUEST_VALIDATION_ERROR` | 请求字段错误 |
| 500 | `QUERY_EXECUTION_ERROR` | 数据库执行错误 |
| 503 | `DATABASE_UNAVAILABLE` | 数据库未初始化或不存在 |

API 不返回 Python Traceback 或 SQLite 原始异常。

## 八、测试与运行证据

验证环境：macOS（Apple Silicon）、Python 3.10.11、项目根目录 `.venv` 隔离环境。运行依赖来自 `backend/requirements.txt`，测试依赖来自 `backend/requirements-dev.txt`；`pip check` 未发现破损依赖。

- 自动化测试：35项通过，0失败。
- Python 编译检查：通过。
- 依赖检查：`No broken requirements found`。
- 数据库重复初始化：客户3、账户4、交易4，外键违规0。
- 真实 Uvicorn：首轮实现验收时启动成功；最终审查修复后再次绑定端口被本机授权额度限制拒绝，未绕过限制重试。
- `GET /health`：HTTP 200。
- 三次真实 `POST /api/v1/query`：均为 HTTP 200，并返回上述数据库结果。
- 架构依赖检查：Application/Ports 不依赖 Adapter、FastAPI、SQLite 或 SQLGlot；API 不反向 import Composition Root。
- 审查修复后的版本由35项单元、集成和 FastAPI TestClient 测试验证；最终真实端口复跑属于当前唯一环境性验证缺口。

## 九、仍使用规则实现的部分

- `YAMLContextResolver` 只做关键词映射，不做 Schema Linking、向量召回或 RAG。
- `RuleSQLGenerator` 只支持3种句式，不调用任何 LLM。
- `TemplateResultFormatter` 根据结果列名生成固定中文模板。
- `NoOpAuditLogger` 保留4类事件调用位置，但不持久化。

## 十、为后续预留的接口

- `LLMProvider.complete`：只接受 `LLMRequest`，返回模型文本和调用元数据。
- `SQLGenerator.generate`：Rule 与未来 LLM Generator 的共同 Port。
- `ContextResolver.resolve`：未来可替换为 Schema Linking 或混合召回。
- `DatabaseExecutor.execute_query`：未来可新增 PostgreSQL Adapter。
- `ResultFormatter.format`：未来可增加图表提示或 LLM 摘要。
- `AuditLogger.record`：未来可替换文件或数据库审计。
- 前端只需调用稳定的 `/api/v1/query` JSON，不需要导入后端代码。

## 十一、当前已知问题

1. 只支持3个问题，不能理解同义表达和多轮上下文。
2. `customer_info` 没有客户姓名，因此首版按 `customer_id` 查询，不能回答“王总”。
3. 账户余额是当前快照，尚不能严谨回答历史余额趋势。
4. LLMProvider 只有 Port，没有真实 Adapter，符合本阶段禁用真实 LLM 的要求。
5. 无网页、图表、RAG、自动修复和推荐追问。
6. Audit 是 No-op，权限只有安全上下文入口，没有完整 RBAC。
7. 依赖采用版本范围，尚无锁文件；团队环境复现仍需加强。
8. 旧 `backend/app/models/query.py` 暂时保留但不在生产路径，后续应在确认无外部使用后移除或归档。

## 十二、独立审查与修复

Sprint 3 完成后按“工程标准”和“规格符合性”两轴审查。首轮发现并修复：

1. 纯空白问题原本会在 `strip` 后变成不支持问题；现改为按去空格后的长度校验，同时成功响应保留原始问题。
2. Pipeline 原本吞掉未知编程异常；现只归一化已知应用异常，未知异常在记录 `query_failed` 后上抛，由 API 全局处理并记录服务器堆栈。
3. API 原本直接 import Composition Root；现由 Bootstrap 向 FastAPI dependency override 注入，API 只保留 Port 类型入口。
4. Executor 原本只有 SQLite 锁等待超时；现增加真正的查询执行期限和中断测试。
5. SQL Safety 的内部细节原本可能进入用户响应；现统一返回通用安全提示。
6. Rule Generator 原本额外支持两个同义句；现严格限制为本阶段三条 Gold Questions。

上述问题均有回归测试。

首轮双轴审查完成后曾发起第二轮独立代理复核，但两个审查任务均因 Codex 使用额度中断，未产生新的审查结论。主工程师随后按同一标准完成最终复核，并重新执行全部35项测试、Python编译、依赖方向检查、数据库计数和外键检查。该中断不计作独立审查已完成。

## 十三、下一阶段建议

先不要同时接 LLM 和复杂网页。推荐先做一个简单 Streamlit 页面调用现有 API，同时扩充到8—10个 Gold Questions，并为同义问法补规则或评测集。这样可以验证产品交互和业务口径，再决定接入真实 LLM Provider。

若团队更重视技术路线，也可以先实现一个 OpenAI-compatible `LLMProvider` Adapter 和 `LLMSQLGenerator`，但必须保留 Rule Generator 作为回退，并先建立 SQL 执行准确率评测。
