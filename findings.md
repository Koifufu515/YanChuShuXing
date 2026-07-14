# 发现与决策

## 需求
- 平台定位：面向银行经营分析场景的智能问数与指标洞察平台。
- 必须形成“业务指标体系 + 数据库建模 + NL2SQL + SQL 校验 + 可视化 + 业务解释 + 推荐追问”的闭环。
- 需要 8-10 张表、七个业务主题、至少 15 个问数案例、四周实施路线和双版本简历表述。
- 需要客观比较题目 14 与题目 22，并说明 22 如何吸收 Agentic AI。

## 研究发现
- 真正的项目壁垒不是 SQL 字符串生成，而是指标口径、字段召回、约束校验和结果可信度。
- 单次 Prompt 难以稳定完成复杂问数，适合拆为“理解—规划—生成—校验—执行—解释”的状态机。
- 数据演示应内置可验证的经营事件，例如某分行逾期率上升、某渠道活跃下降，否则业务解释无法证明有效。
- 首版应优先做 3 个高完成度案例，而不是追求覆盖所有银行业务。

## 技术决策
| 决策 | 理由 |
|------|------|
| 语义层用 YAML 管理指标 | 业务人员可读，也方便程序加载与版本控制 |
| Schema 元数据与 DDL 分离 | DDL 描述物理结构，元数据补充中文别名、敏感级别和关系 |
| 生成前做候选表字段 Top-K 召回 | 缩小上下文，减少字段幻觉和错误 JOIN |
| 生成后解析 AST 做安全检查 | 关键词正则不足以处理注释、子查询和混淆写法 |
| 查询解释基于“结构化结果摘要” | 避免把大表直接交给模型，降低成本和虚构风险 |

## 遇到的问题
| 问题 | 解决方案 |
|------|---------|
| 既要模拟数据又要像真实银行场景 | 使用确定性生成器、业务约束和预埋事件，并明确标注非真实客户数据 |

## 资源
- 用户提供的完整项目要求，作为首版验收清单。

## 2026-07-12 工程审计发现
- 工作区副本与桌面 `农行杯金融科技` 目录的核心代码哈希一致，可在工作区审计后同步两份新增文档。
- `sql/schema.sql` 是真实可执行 DDL；包含 10 张表、外键、检查约束和索引，但没有创建持久化数据库文件或数据装载脚本。
- `backend/app/models/query.py` 是真实 Pydantic 模型，但现有 API 契约偏内部调试，要求返回 intent/plan/safety 等复杂对象，与团队希望冻结的简洁前端契约不一致。
- `backend/app/services/pipeline.py` 是编排骨架：5 个 Protocol 加 `QueryPipeline.run`，没有任何 IntentParser、Retriever、Planner、Generator、Executor、Analyst 的具体实现，也没有错误捕获。
- `backend/app/api/query.py` 的 `get_query_pipeline()` 明确抛出 `RuntimeError`，因此 `/api/v1/ask` 必然无法完成依赖注入。
- `backend/app/main.py` 具有 FastAPI 应用和 `/health` 路由；是否可启动取决于依赖安装和导入路径。
- `backend/app/core/sql_safety.py` 有基于 SQLGlot AST 的实际安全检查，但尚无测试、无角色上下文、无限行/超时/参数策略，也未接入可运行 Pipeline。
- `frontend/` 仅有 README，没有网页、构建配置或可执行前端。
- 当前不存在 LLM Provider、数据库执行器、SQLite 数据库文件、数据生成/装载、结果格式器、审计日志实现或真实 LLM 调用。
- 系统 Python 3.10.11 未预装 FastAPI、Pydantic、PyYAML、SQLGlot、Uvicorn；`from app.main import app` 首次因 `ModuleNotFoundError: fastapi` 失败。
- 在 `/tmp/bankinsight-audit-venv` 中，`backend/requirements.txt` 经联网授权安装成功；依赖声明在当前平台可解析。
- 依赖安装后，Uvicorn 可启动；沙箱内绑定端口被系统拒绝，授权后在 `127.0.0.1:8765` 启动成功，这是运行环境限制，不是项目代码错误。
- `GET /health` 实测 HTTP 200，响应 `{"status":"ok"}`。
- `POST /api/v1/ask` 实测 HTTP 500，堆栈终点为 `get_query_pipeline()` 主动抛出的 `RuntimeError("QueryPipeline providers have not been configured yet.")`。
- OpenAPI 可生成，但当前外部 `QueryResponse` 强制包含内部 `intent`、`plan`、`generated_query`、`safety`，不适合作为首版团队协作的简洁稳定契约。
- SQLite 内存建库实测成功：10 张表、14 个显式索引、`PRAGMA foreign_key_check` 无错误；现有 3 个 `unittest` 均通过。
- `test_negative_account_balance_is_rejected` 同时缺少父表客户和分行记录，当前通过不能单独证明由负余额约束触发；第二阶段应先插入合法父记录再断言负余额失败。
- 现有依赖只有宽版本范围，没有锁文件和 Python 版本声明；不同成员安装时间不同可能得到不同依赖组合。

## 2026-07-14 GitHub 发布审计
- 当前项目根目录不是 Git 仓库，也没有 remote。
- GitHub 正式仓库应保留代码、配置、测试、脚本、正式 Sprint 文档、必要截图和 152KB 确定性模拟数据库。
- 赛事附件、报名表、会议材料、生成 Prompt、Codex 发布指令、Office 临时文件、本地浏览器产物和虚拟环境属于本地资料，应进入 `archive_local/` 或由 `.gitignore` 排除。
- 演示数据库没有姓名、联系方式、证件号或真实银行客户数据；客户编号和业务属性均为可复现模拟值。
- 正式文本未发现真实 API Key、Token、邮箱、身份证号或手机号；`.env` 必须继续只保留在本机。
- README 已采用 Rule First、LLM Extension；旧 Sprint 文档中的 LLM First 是历史记录，不应篡改，但当前状态与任务计划必须明确以 Sprint 5.2 为准。
- 为保证参赛项目安全，GitHub 仓库默认创建为 private，待团队确认后再决定是否公开及采用何种许可证。
