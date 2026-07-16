# 言出数行——银行智能问数与协同分析系统

言出数行面向银行经营分析场景，为不会编写 SQL 的业务人员提供自然语言问数、指标口径匹配、安全查询、结果解释和协同分析能力。系统以业务语义和安全治理为前提，不把“模型生成 SQL”当作完整产品。

> 当前阶段：正式赛题数据迁移与团队并行开发。公开仓库保留可运行的 Demo 技术基线；官方数据、标准答案和敏感评测结果只在受控环境使用。

## 项目定位

用户提出经营分析问题后，系统识别机构、指标、时间和比较方式，匹配官方指标语义与数据库结构，生成 SQL 并通过安全检查，最后返回查询结果、业务结论和可解释的执行信息。

```text
自然语言问题
  -> 指标与 Schema 上下文
  -> Rule First / LLM Extension
  -> SQL Safety
  -> 只读数据库执行
  -> 结果格式化与业务解释
  -> 网页展示与评测留痕
```

核心价值：

- 统一指标口径，减少同一指标的多种解释；
- 标准问题优先使用已验证规则，复杂问法再由大模型扩展；
- 所有 SQL 统一经过只读、表范围、敏感字段和单语句检查；
- 查询路径、模型语义、耗时和失败原因可解释；
- 固定题库支持版本回归，避免只展示少量成功案例。

## 正式数据边界

正式赛题阶段固定使用五张官方表：

1. 机构信息表；
2. 指标清单表；
3. 衍生维度说明；
4. 指标数据表；
5. 问题答案清单。

五张表分别承担机构维度、指标口径、衍生规则、经营事实和评测基准职责。问题答案清单是评测资产，不进入业务查询数据库，也不得用于在 Rule、Prompt 或前端中硬编码测试答案。正式字段、主外键和数据库结构由 Issue #4 审计确认后写入[数据库与指标字典](docs/数据库与指标字典.md)，当前文档不会提前编造字段。

官方原始文件、标准答案、完整字段映射和敏感查询结果不上传公开 GitHub。公开仓库仅保存代码、无数据 ETL、脱敏后的结构说明和汇总评测结果。

## 系统架构

后端采用轻量 Ports & Adapters 架构，Pipeline 只负责流程编排。

```text
Streamlit Frontend
        |
        v
FastAPI /api/v1/query
        |
        v
QueryPipeline
  |-- ContextResolver
  |-- SQLGenerator
  |     |-- RuleSQLGenerator
  |     |-- LLMSQLGenerator -> DeepSeek LLMProvider
  |     `-- HybridSQLGenerator（Rule First）
  |-- SQLSafetyChecker -> SQLGlot
  |-- DatabaseExecutor -> Readonly SQLite
  |-- ResultFormatter
  `-- AuditLogger
```

模块通过稳定接口通信。前端只调用后端 API，不直接读取 Excel 或数据库；Rule 与 LLM 生成的 SQL 必须经过同一安全层；API 不向用户暴露模型原始响应、数据库异常或 Python Traceback。

## 当前开发状态

### Demo 技术基线

`demo-baseline` Tag 与 Release 保存了正式数据迁移前的可运行版本。该版本验证了十张模拟业务表、三条 Demo 问题、Rule First Hybrid、两阶段 DeepSeek、SQL Safety、只读执行器、模板解释、Metadata、Streamlit 页面和自动化测试。

这些资源仍保留在当前主线中，供前端开发、公开演示、CI 和迁移回归使用：

- `data/processed/bankinsight.db`
- `sql/schema.sql`
- `config/schema.yml`
- `config/metrics.yml`

它们被明确标记为 Demo 技术基线，不代表正式比赛的数据范围、指标体系或问题覆盖。正式数据库完成建库、联调和回归验收前，不删除或覆盖这些资源。

### 正式赛题阶段

当前工作围绕六项 GitHub Issue 展开：

| Issue | 工作流 | 主要责任 |
|---|---|---|
| #1 | 项目统筹、技术集成与仓库治理 | 稳定主干、接口审核、跨模块集成与发布 |
| #2 | 基于官方问题与固定数据的产品功能及交互方案 | 产品流程、结果层级、推荐问题与演示路径 |
| #3 | 前端实现与产品集成 | 页面实现、API 对接、状态与异常展示 |
| #4 | 五张官方表的数据审计、规范化入库与查询底座建设 | 数据字典、清洗映射、ETL、约束与对账 |
| #5 | 官方题库语义映射、衍生口径整理与题库异常审核 | 题库表达映射、衍生与复合口径、异常审核；不负责SQL、路由和测试执行 |
| #6 | 固定题库回归评测与版本验收体系 | 正确率、执行成功率、耗时、失败分类和版本差异 |

依赖顺序为：#4、#5、#6 先形成数据、语义和评测基础；#2、#3 再完成产品与前端迁移；#1 负责最终集成和验收。详细计划见 [task_plan.md](task_plan.md)。

## 查询处理链路

默认 `hybrid` 模式采用 Rule First：

```text
命中已验证 Rule -> 参数化 SQL -> Safety -> Database
未命中 Rule -> LLM 语义解析 -> LLM SQL -> Safety -> Database
LLM 失败 -> 结构化错误，流程结束
```

系统还保留 `rule` 和 `llm` 两种模式用于确定性演示与模型测试。LLM 失败后不会反向尝试 Rule；缺少条件、指标不支持、模型超时或 SQL 不安全时返回明确错误。

## 快速运行 Demo

已验证环境为 macOS Apple Silicon、Python 3.10.11。请始终使用项目根目录自己的 `.venv`。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pip install -r frontend/requirements.txt

PYTHONPATH=backend .venv/bin/python -m app.adapters.database.init_db
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端启动网页：

```bash
PYTHONPATH=. .venv/bin/python -X faulthandler -m streamlit run frontend/app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.fileWatcherType none \
  --browser.gatherUsageStats false
```

访问地址：

- 产品页面：`http://127.0.0.1:8501`
- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI：`http://127.0.0.1:8000/docs`

Generator 配置：

```text
BANKINSIGHT_GENERATOR_MODE=rule
BANKINSIGHT_GENERATOR_MODE=llm
BANKINSIGHT_GENERATOR_MODE=hybrid
```

内部环境变量、Python 类名、数据库文件名和 API 路径中的 `BankInsight` 暂时保留，以避免品牌改名引起无意义的兼容性风险；所有对外页面和正式文档统一使用“言出数行”。

## 自动化验证

```bash
.venv/bin/python -m pip check
PYTHONPATH=backend:. .venv/bin/python -m compileall -q backend frontend tests scripts
PYTHONPATH=backend:. .venv/bin/python -m unittest discover -s tests
PYTHONPATH=. .venv/bin/python scripts/stability_check.py --iterations 60
```

真实 DeepSeek 连通性测试需要本地密钥，默认不进入自动化测试：

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/deepseek_smoke_test.py
```

## 正式文档

- [项目完整方案](docs/项目完整方案.md)
- [接口契约](docs/接口契约.md)
- [数据库与指标字典](docs/数据库与指标字典.md)
- [评测规范](docs/评测规范.md)
- [05号业务语义与题库标准](docs/05_业务语义与题库标准.md)
- [竞赛数据与智算平台资料使用说明](docs/竞赛数据与智算平台资料使用说明.md)
- [团队分工与协作规范](docs/团队分工与协作规范.md)
- [贡献与提交流程](CONTRIBUTING.md)
- [安全与赛事数据规则](SECURITY.md)

## 后续计划

1. 完成五张官方表审计、字段映射和双环境数据库方案；
2. 完成官方题库语义映射、衍生口径和异常审核，由技术成员据此建立Gold SQL与固定回归基准；
3. 将正式数据接入现有 Context、Generator、Safety 和 Executor 主链路；
4. 依据官方问题设计产品模块、推荐问题和图表；
5. 完成端到端评测、性能优化与答辩版本收口。

当前不提前引入 RAG、向量数据库、多 Agent、复杂权限体系、桌面端或移动端，避免在数据与评测基座未稳定前扩大范围。

## 仓库与安全

- GitHub：[Koifufu515/YanChuShuXing](https://github.com/Koifufu515/YanChuShuXing)
- Demo 基线：[demo-baseline Release](https://github.com/Koifufu515/YanChuShuXing/releases/tag/demo-baseline)
- Issues：[团队任务](https://github.com/Koifufu515/YanChuShuXing/issues)

密钥、Token、`.env`、官方数据、标准答案和敏感结果不得提交。详细规则见 [SECURITY.md](SECURITY.md)。

## 许可证

项目暂未选择开源许可证。在团队确认前，请勿用于外部再发布或商业用途。
