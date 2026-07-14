# Changelog

## Unreleased

### Team workflow

- 新增六人团队职责边界、交叉审核矩阵、首轮六项任务及可判断的验收标准。
- 新增功能、数据、测试、文档四类 GitHub Issue 表单和统一 Pull Request 模板。
- 新增 CODEOWNERS，精确保护应用层、Ports、Composition Root、数据库契约、指标配置和发布入口。
- 扩充贡献指南，明确 Issue 认领、独立分支、PR、Review、Merge、主分支同步和冲突处理流程。
- 本次仅建立团队协作框架，不新增或修改业务功能。

### Repository audit

- 以0.5.2实际代码为基准重写当前项目方案、接口契约和数据库指标字典，新增仓库一致性审计报告。
- 将早期架构、Sprint 和故障文档统一标记为历史记录，并指向当前 README 与契约。
- 移除无人引用的旧 Query Model、Pipeline 兼容转发、三份已完成的 Agent 计划和两张重复旧截图。
- 将 Safety 内部报告模型归入当前 Safety 模块，并将 FastAPI OpenAPI 版本统一为0.5.2。
- 校准 task plan、progress、README、19项指标状态、三条 Gold 问题和公开仓库状态。

### Repository

- 整理适合团队协作的 GitHub 发布结构，补充贡献指南、安全说明和 Python 版本声明。
- 扩充 `.gitignore`，排除本地密钥、虚拟环境、缓存、诊断文件、个人材料和生成输出。
- 确认 FastAPI 0.139 的 TestClient 使用 `httpx2>=2.5,<3.0`，避免回退旧 `httpx` 产生弃用警告。
- 更新 README 与前端说明，使启动方式、Rule First Hybrid、当前能力和限制与 v0.5.2 一致。

## v0.5.2 - 2026-07-14

### Changed

- Hybrid 查询路由由“LLM 优先、Rule 回退”调整为“Rule First、LLM Extension”。
- 三条已验证查询命中 Rule 时不调用 DeepSeek；规则未命中时才进入两阶段 LLM 生成。
- LLM 超时、缺少参数、未支持指标和非法输出直接返回结构化错误，不再尝试 Rule。

### Added

- Metadata 新增 `rule_matched`、`route` 和 `failure_reason`，旧 `fallback` 字段继续保留兼容但不再用于新路由。
- Safety 拒绝统一记录 `failure_reason=unsafe_sql`。
- Streamlit 技术详情新增查询路径、规则命中和失败原因中文展示。
- 新增 Rule 命中跳过模型、Rule 未命中调用模型、超时、澄清、未支持指标和安全拒绝测试。

### Unchanged

- FastAPI 请求与响应顶层结构、SQL Safety、SQLite、Schema、Metrics 和前端查询 API 保持不变。
- QueryPipeline 不包含固定问题判断，路由仍封装在可替换的 `SQLGenerator` Adapter 中。

## v0.5.0 - 2026-07-13

### Changed

- Streamlit 首页重构为银行经营分析平台布局，增加六个业务模块导航、经营概览和六个推荐问题。
- 查询结果顺序调整为业务结论、关键指标、查询结果、生成 SQL、技术详情。
- 页面可见产品语言统一为中文，技术模式、模型、字段和指标均提供中文映射。
- 结果表格增加中文列名与金额单位格式，仍使用安全 HTML 渲染。

### Added

- 新增只读经营概览访问层，从 Demo SQLite 实时统计有效客户、账户、交易和理财产品数量。
- 新增 `.streamlit/config.toml`，使用官方最小工具栏模式并隐藏详细异常。
- 新增桌面首页、真实查询结果和移动端验收截图。
- 新增 Sprint 5 前端产品契约与 KPI 数据测试。

### Unchanged

- FastAPI、QueryPipeline、Generator、SQL Safety、数据库结构、演示数据和 `/api/v1/query` 行为均未修改。
- Arrow 系统内存池、HTML 表格和纯数据 Session State 稳定性修复完整保留。

## v0.4.3 - 2026-07-13

### Added

- `/api/v1/query` 成功响应新增向后兼容的可选 `metadata`，区分配置模式与实际 Generator。
- Rule、LLM、Hybrid 三种路径统一记录 Provider、模型、语义、置信度、模型耗时和稳定回退代码。
- Streamlit 业务解释下方新增默认折叠的“技术详情”，兼容 Metadata 缺失和空字段。
- 指标语义层新增成功交易笔数、交易流入、交易流出和净交易流四项口径。
- 新增可解释性与交易语义自动化测试及真实页面截图。

### Verified

- 真实 DeepSeek 将交易问题识别为 `monthly_transaction_summary / transaction`，生成参数化 SQL并返回3笔交易、净流入5万元，未发生规则回退。
- 75项自动化测试、60次API循环、20次浏览器交替查询和30次三问题浏览器循环通过。
- 保留 Arrow 系统内存池、HTML结果表格和纯数据 Session State；未新增 macOS Python Crash Report。

### Unchanged

- QueryPipeline 仍只负责编排；数据库结构、演示数据、三个业务问题和确定性业务解释均未改变。

## v0.4.2-stability - 2026-07-13

### Fixed

- 定位 Streamlit 进程级崩溃到 PyArrow 25 的 Mimalloc 分配与表格序列化原生路径。
- 结果表格改用 HTML 安全转义渲染，避开 `st.dataframe` 的 Arrow 转换与 IPC 序列化。
- Streamlit 导入前将 `ARROW_DEFAULT_MEMORY_POOL` 设置为 `system`。
- Session State 只保存 JSON 兼容数据，失败请求会清理旧结果并允许后续查询恢复。
- 项目运行环境固定为桌面项目根目录 `.venv`，不再复用其他工程的虚拟环境。

### Tested

- 新增连续查询、连接恢复、Hybrid 超时恢复和页面状态测试。
- 69项自动化测试、60次真实 API 循环、20次浏览器交替查询和30次浏览器三问题循环全部通过。
- 修复后未出现新的 macOS Python Crash Report。

## v0.4.2 - 2026-07-12

### Added

- DeepSeek Chat Completions Provider，包含超时、网络、HTTP、空响应和格式异常归一化。
- 两阶段 `LLMSQLGenerator`：先解析银行业务语义，再结合 Schema/Metric Context 生成 SQLite SQL。
- `HybridSQLGenerator`：DeepSeek 失败时仅对现有三个固定问题回退 `RuleSQLGenerator`。
- `rule`、`llm`、`hybrid` 三种环境配置模式和可公开的 `.env.example`。
- Fake Provider 自动化测试、危险 SQL 安全拒绝测试和真实 DeepSeek Smoke 脚本。

### Security

- 新增 `.gitignore` 隔离 `.env`、虚拟环境、缓存和本地测试产物。
- Provider 不向 API 暴露密钥、第三方响应体、传输异常或内部堆栈。

### Unchanged

- QueryPipeline 编排、数据库结构、演示数据、RuleSQLGenerator 和 v1 请求结构保持不变。

## v0.4.0 - 2026-07-12

### Added

- Streamlit 单页产品 Demo，通过 `/api/v1/query` 调用真实后端。
- 三个示例问题、加载状态、SQL 代码块、结果表格和业务解释。
- Warning、统一 Error、版本、数据库、Generator、请求耗时和 Request ID 展示。
- 前端 API 客户端测试与桌面、移动端浏览器验收截图。

### Changed

- README 增加前端依赖、双服务启动方式和演示入口。
- 示例问题切换时清除旧结果，避免问题与结果暂时不一致。

### Unchanged

- Sprint 3 的 Pipeline、Application、Ports、Adapters、Composition Root、数据库结构和 Rule SQL Generator 均未修改。
