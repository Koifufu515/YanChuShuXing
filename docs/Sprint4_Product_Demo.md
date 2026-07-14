# Sprint 4.1 产品化 Demo 实施记录

> **文档类型：历史实施记录，不代表当前页面。**
> 当前页面已经过 Sprint 5、5.1 重构；页面结构和能力以根目录 `README.md` 与 `docs/Sprint5_Product_Demo_Redesign.md` 为准。

## 页面整体结构

页面采用单页工作台：顶部展示 BankInsight 名称和产品定位；中部提供三个示例问题、自然语言输入框和查询按钮；查询完成后依次展示生成 SQL、结果表格、业务解释与运行信息。Warning 使用黄色提示，Error 使用统一红色提示，不展示 Python Traceback 或数据库原始异常。

Sprint 4.1 的重复页面截图已在仓库清理时移除；当前页面效果见 [Sprint 5 首页截图](assets/bankinsight-sprint5-home.png)。原截图仍可从 Git 历史追溯。

## 技术选型

选择 Streamlit 1.59.1，而非 React、Vue 或 Node.js。原因是当前目标仅为竞赛本地 Demo：Streamlit 能直接使用团队熟悉的 Python，部署依赖少，并可在不改变 FastAPI 后端的前提下快速完成产品展示。

前端只有两层：

```text
Streamlit View
    -> BankInsightClient
    -> POST /api/v1/query
    -> Sprint 3 Query Pipeline
```

页面不连接 SQLite，不生成 SQL，不复制指标规则。SQL、表格数据、摘要、Warning、Error 和 Request ID 均来自 API；页面显示的耗时是从前端发出请求到收到完整响应的端到端耗时。

## 运行方式

已验证环境：macOS Apple Silicon、Python 3.10.11、Streamlit 1.59.1。首次运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pip install -r frontend/requirements.txt
PYTHONPATH=backend .venv/bin/python -m app.adapters.database.init_db
```

分别启动后端和网页：

```bash
PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
PYTHONPATH=. .venv/bin/python -m streamlit run frontend/app.py --server.port 8501
```

浏览器访问 `http://127.0.0.1:8501`。如后端地址不同，可设置 `BANKINSIGHT_API_URL`。

## 与 Sprint 3 相比的新增内容

1. 新增面向评委的单页网页，不再依赖 Swagger 或 Postman。
2. 新增三个示例按钮、加载状态和可编辑问题输入框。
3. 新增 SQL、标准表格、业务解释、Warning 和 Error 的固定展示顺序。
4. 新增版本、数据库、Generator、耗时和 Request ID 运行信息。
5. 新增独立 HTTP 客户端及成功、业务错误、连接失败测试。
6. 新增真实浏览器交互与桌面、移动端布局检查。

## 验收结果

- 三个固定问题均通过页面调用真实 `/api/v1/query` 并返回成功结果。
- 不支持的问题显示 `UNSUPPORTED_QUESTION`，未暴露内部异常。
- SQL 使用 Streamlit 代码块展示，内置复制操作。
- 结果使用数据表格展示，解释来自 Template Result Formatter。
- 页面在 1440 像素桌面视口和 390 像素窄屏视口未出现控件重叠；长 SQL 在窄屏代码区域内滚动。
- Streamlit 自动化过程中进程会随工具会话回收；这属于验收环境行为，本地终端正常运行时服务持续可用。
- Sprint 3 回归测试与 Sprint 4.1 新增测试合计40项通过。

## 当前限制

1. 仍只支持 Sprint 3 的三个规则问题。
2. Generator 仍为 Rule Generator，未接入真实 LLM。
3. 查询耗时为前端端到端耗时，v1 API 尚未单独返回数据库执行耗时。
4. 当前没有图表、历史会话、推荐追问、指标口径面板或登录权限。
5. Warning 展示逻辑已实现，但现有三个成功问题通常不会产生 Warning。

## Sprint 4.2 建议

优先补充产品层而不是接入复杂 Agent：增加指标口径抽屉、推荐追问和简单会话历史，同时明确 v1 API 是否需要新增可选 `metadata` 字段。完成产品流程后，再实现 `LLMSQLGenerator` 并与当前规则生成器做准确率和失败回退对比。
