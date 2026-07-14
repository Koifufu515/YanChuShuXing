# BankInsight 协作指南

感谢参与 BankInsight。项目采用轻量端口与适配器架构，协作目标是让各模块能够独立开发，同时保持指标口径、API 契约和安全规则一致。

## 本地环境

在项目根目录创建独立环境，不要复用其他工程的 `.venv`：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pip install -r frontend/requirements.txt
```

复制示例配置并仅在本机填写密钥：

```bash
cp .env.example .env
```

`.env`、API Key、Token、Cookie 和个人凭据禁止提交。提交前应使用 `git status --ignored` 确认它们处于忽略状态。

## 目录职责

| 领域 | 主要目录 | 责任边界 |
|---|---|---|
| 前端产品 | `frontend/`、`.streamlit/` | 页面交互、中文展示、API 调用和错误恢复 |
| 业务指标 | `config/metrics.yml`、`docs/数据库与指标字典.md` | 指标定义、口径、维度、主题和示例问法 |
| 数据模型 | `sql/`、`config/schema.yml`、`data/` | DDL、字段语义、表关系、确定性模拟数据 |
| 模型生成 | `backend/app/adapters/generation/`、`backend/app/adapters/llm/` | Rule、LLM、Hybrid 路由和 Provider |
| 安全执行 | `backend/app/adapters/safety/`、`backend/app/adapters/database/` | SQL 安全检查、只读查询、超时和限行 |
| 应用编排 | `backend/app/application/`、`backend/app/ports/`、`backend/app/bootstrap/` | 稳定接口、Pipeline 和依赖组装 |
| 测试文档 | `tests/`、`docs/`、`README.md` | 回归测试、架构记录、运行说明和变更记录 |

不同模块只通过 Port 和冻结的数据结构通信。不要在前端、Pipeline 或 API 路由中复制 SQL 生成和数据库查询逻辑。

## 修改同步规则

### 修改业务指标

必须同步检查：

1. `config/metrics.yml` 中的机器可读定义；
2. `docs/数据库与指标字典.md` 中的业务说明；
3. Context Resolver 的召回规则；
4. 对应 Gold SQL、结果格式器和自动化测试；
5. README 或 Sprint 文档中的支持范围。

### 修改数据库结构

必须同步检查：

1. `sql/schema.sql`；
2. `config/schema.yml`；
3. `backend/app/adapters/database/init_db.py` 的确定性演示数据；
4. Executor、Safety 允许表与字段配置；
5. Schema、外键和端到端测试；
6. 数据库与指标字典。

### 新增标准问题

每个标准问题必须同时提供：

- 清晰的业务指标口径；
- 参数解析规则；
- 经过人工核验的 Gold SQL；
- 确定性测试数据和预期结果；
- Rule、Safety、Formatter、API 端到端测试；
- 推荐问法与当前支持范围说明。

## 提交前验证

```bash
.venv/bin/python -m pip check
PYTHONPATH=backend .venv/bin/python -m compileall -q backend frontend tests scripts
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=backend .venv/bin/python -m app.adapters.database.init_db
```

前端改动还应启动 FastAPI 和 Streamlit，至少验证三个标准问题、一个错误场景和窄屏布局。

## 分支与 Pull Request

- 从最新主分支创建短生命周期功能分支；一个 PR 只处理一个明确目标。
- PR 说明应包含：问题背景、改动范围、接口影响、测试证据、截图或响应示例、风险和回滚方式。
- 不要把格式化、无关重构和业务功能混在同一个 PR。
- 核心 `backend/app/application/`、`backend/app/ports/` 和 `backend/app/bootstrap/container.py` 的修改必须由技术负责人审核。
- 合并前必须确认真实密钥、个人信息、日志、缓存和本地数据库副本未进入变更列表。
