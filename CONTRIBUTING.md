# 言出数行——银行智能问数与协同分析系统 协作指南

感谢参与“言出数行”。项目采用轻量端口与适配器架构，协作目标是让各模块能够独立开发，同时保持指标口径、API 契约和安全规则一致。

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
| 业务指标 | `config/metrics.yml`、`docs/数据库与指标字典.md` | Demo 配置维护；正式指标映射、口径和审核记录 |
| 数据模型 | `sql/`、`config/schema.yml`、`data/` | Demo 基线；正式五表 DDL、ETL、字段语义和双环境配置 |
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
4. 对应结果格式器、官方答案判分规则和自动化测试；
5. README、评测规范和正式项目方案中的支持范围。

### 修改数据库结构

必须同步检查：

1. `sql/schema.sql`；
2. `config/schema.yml`；
3. Demo 初始化或正式 ETL；
4. Executor、Safety 允许表与字段配置；
5. Schema、外键和端到端测试；
6. 数据库与指标字典。

### 新增标准问题

每个标准问题必须同时提供：

- 清晰的业务指标口径；
- 参数解析规则；
- 可追溯的业务口径和官方答案判分规则；
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

前端改动还应启动 FastAPI 和 Streamlit，验证受影响问题、一个错误场景和主要比赛视口。正式数据页面不得直接读取 Excel 或数据库。

## Issue 认领

1. 所有工作先创建或认领 GitHub Issue，不从群聊中的一句话直接开始改代码。
2. 认领时在 Issue 留言，由项目负责人设置负责人；存在依赖时先确认前置任务状态。
3. Issue 必须写清背景、交付物、涉及文件、验收标准、依赖任务和负责人角色。
4. 一个 Issue 对应一个分支和一个 Pull Request。新发现的无关问题另开 Issue。

## 分支命名

普通成员不能直接向 `main` 提交代码。开始任务前先同步主分支，再创建短生命周期分支：

```bash
git switch main
git pull --ff-only origin main
git switch -c <类型>/<简短任务名>
```

每项任务都从最新 `main` 创建独立分支，一个任务只对应一个分支和一个 Pull Request。推荐前缀：`product/`、`feature/`、`data/`、`business/`、`test/`、`fix/`、`docs/` 和 `chore/`。当前任务及依赖见 [task_plan.md](task_plan.md) 和 GitHub Issues。

## Pull Request

- 推送独立分支后创建 PR，以 `main` 为目标，关联对应 Issue，并完整填写仓库模板。
- PR 标题采用“英文类型前缀 + 中文任务说明”，例如 `data: 建设正式指标数据库`、`feature: 实现智能问数页面`、`test: 建立官方题库批量评测`。
- PR 说明必须包含：问题背景、改动文件、接口和数据库影响、实际验证、截图或数据证据、风险与回滚方式。
- 不要把格式化、无关重构和业务功能混在同一个 PR。
- 合并前必须确认真实密钥、个人信息、官方原始数据、标准答案、敏感评测结果、日志、缓存和本地数据库副本未进入变更列表。
- 作者不能把自己的自测当作审核；至少由一名相关角色交叉审核。

## 审核要求

| 变更 | 交叉审核角色 |
|---|---|
| 产品方案 | 前端负责人、业务负责人 |
| 前端实现 | 产品负责人、测试负责人 |
| 数据库与数据 | 业务负责人、测试负责人 |
| 业务指标与语义口径 | 数据负责人、项目负责人 |
| 测试、安全与文档 | 项目负责人 |

以下核心路径必须由项目负责人 `@Koifufu515` 审核：`backend/app/application/`、`backend/app/ports/`、`backend/app/bootstrap/container.py`、`sql/schema.sql`、`config/schema.yml`、`config/metrics.yml`、`README.md` 和 `CHANGELOG.md`。以 `.github/CODEOWNERS` 为准。

## 合并与发布

1. 审核意见全部解决、验收证据完整、自动化检查通过后，才可合并。
2. 由项目负责人完成最终合并和版本整合；普通成员不得绕过 PR 向 `main` 推送。
3. 合并后由任务负责人确认 Issue 自动关闭，删除已合并的任务分支，并同步最新 `main`。
4. 涉及版本说明时同步更新 CHANGELOG；业务能力只有合并后才能在 README 或答辩材料中标记为已完成。

## 同步主分支与冲突处理

PR 提交前同步最新主分支：

```bash
git fetch origin
git merge origin/main
```

团队成员暂不使用强制推送或自行改写共享历史。只解决自己职责范围内且理解清楚的冲突；涉及 Pipeline、Ports、数据库结构、公共指标配置或多人共同编辑的文件时，邀请项目负责人和相关模块负责人共同处理。禁止使用 `git reset --hard`、删除他人代码或强制推送来规避冲突。

完整角色边界、审核矩阵和主分支保护建议见 [团队分工与协作规范](docs/团队分工与协作规范.md)。
