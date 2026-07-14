# Sprint 5 Product Demo 重构记录

> **文档类型：历史实施记录。**
> 本文记录 Sprint 5 页面重构；后续 Sprint 5.1 增加场景选择器，Sprint 5.2 修改 Hybrid 路由。当前产品行为以根目录 `README.md` 和代码为准。

## 目标与边界

本阶段只重构 Streamlit 产品体验，不增加后端能力。FastAPI、QueryPipeline、Rule/LLM/Hybrid Generator、SQL Safety、数据库结构、Demo 数据和 `/api/v1/query` 行为均保持不变。

## 页面结构

新版单页从上到下分为：

1. BankInsight 品牌与中文副标题；
2. 客户、存款、贷款、理财、风险、经营六个业务模块导航；
3. 四项经营概览；
4. 大尺寸智能问数输入区与开始分析按钮；
5. 六个可扩展推荐问题；
6. 查询后的业务结论、关键指标、查询结果、生成 SQL 和折叠技术详情。

页面不是营销落地页，也没有聊天气泡、渐变、动画或科技装饰，视觉重点放在经营指标、查询入口和结果解释。

## 经营概览

`frontend/kpi_repository.py` 使用 SQLite 只读 URI 打开现有 Demo 数据库，每次只返回普通整数并立即关闭连接。当前真实数据为有效客户2户、账户4个、交易4笔、理财产品0个。数据库不可用时页面显示“暂不可用”，不会写入数据或影响查询 API。

## 产品语言

除 BankInsight 品牌名和 SQL 内容外，页面标题、按钮、提示、表格字段、技术详情和运行信息均使用中文。运行模式、执行器、模型提供方、模型版本、业务领域、语义意图和指标名称在展示层完成中文映射，API Metadata 保持原契约。

## Streamlit 界面隐藏

`.streamlit/config.toml` 使用官方支持的：

- `toolbarMode = "minimal"`；
- `showErrorDetails = "none"`；
- `showSidebarNavigation = false`；
- `headless = true`；
- `fileWatcherType = "none"`。

页面 CSS 进一步隐藏 Streamlit 页头、工具栏、主菜单和页脚。未修改 Streamlit 源码。真实浏览器检查中 Deploy 和主菜单元素数量均为0。

## 稳定性保留

- Streamlit 导入前仍设置 `ARROW_DEFAULT_MEMORY_POOL=system`；
- 页面仍不调用 `st.dataframe`；
- 结果表格继续使用HTML转义；
- Session State只保存字典、列表、字符串和数字；
- KPI数据库连接不进入 Session State，查询后自动关闭。

## 视觉验收

- 桌面首页：`docs/assets/bankinsight-sprint5-home.png`；
- 真实查询结果：`docs/assets/bankinsight-sprint5-result.png`；
- 390像素移动端：`docs/assets/bankinsight-sprint5-mobile.png`。

桌面与移动端的页面滚动宽度均等于视口宽度，没有横向溢出。移动端经营指标自动变为两列，推荐问题自动纵向排列。

## 当前限制

1. 六个推荐问题中，后三个是产品扩展入口，当前后端仍会按既有契约返回不支持提示；Sprint 5 没有越界增加业务查询。
2. 经营概览直接读取本地 Demo SQLite，仅用于单机竞赛演示；正式部署应通过后端概览接口获取。
3. 当前未建立完整设计规范；下一步应先形成《BankInsight Design Guideline》，再开发其他页面或跨端版本。
