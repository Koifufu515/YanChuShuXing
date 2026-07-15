# Changelog

本文件从正式赛题数据迁移阶段开始记录面向发布的变化。早期逐 Sprint 开发细节保存在 Git 历史和 `demo-baseline` Release 中，不再作为当前主线文档维护。

## Unreleased

### 正式赛题阶段

- 作品正式名称统一为“言出数行——银行智能问数与协同分析系统”，GitHub 仓库更名为 `Koifufu515/YanChuShuXing`。
- 建立 `demo-baseline` Tag 与 Release，固定正式数据迁移前的可运行技术基线。
- 重写 README、正式项目方案、任务计划、数据库与指标字典和评测规范，明确五张官方表的数据边界。
- 原地更新 GitHub Issue #1 至 #6，形成项目统筹、产品方案、前端集成、官方数据治理、问题语义与 Gold SQL、固定题库评测六项工作流。
- 明确问题答案清单是受控评测资产，与业务查询数据库隔离；官方数据、标准答案和敏感结果不得进入公开仓库。
- 清理一次性架构评审、Sprint 实施、故障排查、阶段性审计、旧截图和重复进度文件；仍有效结论已迁入正式文档。
- 内部 Python 标识、环境变量、API 路径和 Demo 数据库文件名中的 `BankInsight` 暂时保留，以维持代码兼容。

## Demo 技术基线 - 2026-07-14

- 完成十张模拟业务表和三条 Demo 问题的端到端验证。
- 完成轻量 Ports & Adapters、Rule First Hybrid、两阶段 DeepSeek、SQL Safety、只读 SQLite、模板业务解释、Metadata 和 Streamlit 页面。
- 完成独立虚拟环境、PyArrow 稳定性修复、错误恢复和自动化测试。
- 该版本由 [`demo-baseline`](https://github.com/Koifufu515/YanChuShuXing/releases/tag/demo-baseline) 固化，仅作为开发、公开演示和迁移回归基线，不代表正式比赛数据与业务范围。
