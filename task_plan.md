# 任务计划：银行业智能问数与指标洞察平台

## 目标
完成一个可继续开发、可答辩演示、可写入数据分析或 AI 产品实习简历的 BankInsight 项目初始框架，覆盖业务方案、指标语义层、数据库模型、NL2SQL 链路、安全治理和演示案例。

## 当前阶段
阶段 15

## 各阶段

### 阶段 1：需求与边界
- [x] 解析 13 个交付章节
- [x] 明确首版是完整方案加可执行工程骨架
- [x] 确认首版允许模拟银行数据，但数据生成必须遵循业务约束
- **状态：** complete

### 阶段 2：业务与产品设计
- [x] 完成项目定位、痛点、价值和命名
- [x] 完成系统模块、输入输出与连接关系
- [x] 完成七大业务主题指标体系与 15 个典型场景
- [x] 完成竞品题目比较、四周路线和简历包装
- **状态：** complete

### 阶段 3：技术与数据框架
- [x] 建立 10 张业务表的 SQLite DDL
- [x] 建立机器可读指标目录与 Schema 元数据
- [x] 建立 NL2SQL 流水线、SQL 安全校验和 API 骨架
- [x] 建立前端信息架构与配置入口
- **状态：** complete

### 阶段 4：验证
- [x] 校验目录、配置和 SQL DDL
- [x] 验证 SQL 安全规则运行时用例（已在后续阶段完成并持续回归）
- [x] 核对文档需求覆盖率与演示闭环
- **状态：** complete

### 阶段 5：交付
- [x] 汇总首版成果与下一阶段优先级
- [x] 给出可点击文件入口
- **状态：** complete

### 阶段 6：工程审计与接口冻结
- [x] 逐文件审计现有实现、占位与依赖
- [x] 实测 SQLite、测试、后端启动、`/health` 与查询接口
- [x] 新建 `docs/工程审计与原型实施计划.md`
- [x] 新建 `docs/接口契约.md`
- [x] 核对文档与证据并同步到桌面项目目录
- **状态：** complete

### 阶段 7：Sprint 3 架构实施与最小纵向原型
- [x] 建立纯应用模型、错误与七个独立 Ports
- [x] 建立确定性 SQLite 数据库与只读 Executor
- [x] 实现 YAML Resolver、Rule Generator、Safety、Formatter、NoOp Audit
- [x] 实现只负责编排的 Pipeline 与唯一 Composition Root
- [x] 修复 `/api/v1/query` 并保留 `/api/v1/ask` 兼容别名
- [x] 完成六类测试、真实 HTTP 验收和实现记录
- [x] 完成两轴审查、回归验证并同步桌面项目
- **状态：** complete

### 阶段 8：Sprint 4.1 产品化 Demo
- [x] 实现只调用 `/api/v1/query` 的轻量 Streamlit 单页
- [x] 展示 SQL、真实结果、业务解释、警告、错误和运行信息
- [x] 验证三个固定问题及异常状态
- [x] 完成浏览器视觉检查、页面截图和文档同步
- **状态：** complete

### 阶段 9：Sprint 4.2 DeepSeek 与 Hybrid Generator
- [x] 建立安全配置加载和 DeepSeek LLMProvider
- [x] 实现业务语义解析与 SQL 生成两阶段 LLMSQLGenerator
- [x] 实现 Rule、LLM、Hybrid 三模式与可靠回退
- [x] 完成 Fake Provider、模式兼容、安全拒绝和全量回归测试
- [x] 执行真实 DeepSeek Smoke Test 并更新文档
- **状态：** complete

### 阶段 10：Streamlit Segmentation Fault 稳定性专项
- [x] 在桌面项目根目录建立独立 `.venv` 并核对关键依赖
- [x] 收集并分析 macOS Crash Report 与 faulthandler 运行信息
- [x] 隔离 Arrow 表格序列化路径并切换系统内存池
- [x] 保证 Session State 仅保存 JSON 兼容数据
- [x] 增加连续查询、失败恢复和 Hybrid 超时恢复测试
- [x] 完成真实浏览器20次交替查询与30次三问题循环
- [x] 完成60次真实 API 稳定性复验和69项全量回归
- [x] 新增完整排查文档并更新运行说明
- **状态：** complete

### 阶段 11：Sprint 4.3 查询链路可解释性与交易语义
- [x] 新增统一、框架无关的查询 Metadata 模型
- [x] 让 Rule、LLM、Hybrid 记录配置模式与实际 Generator
- [x] 以可选字段透传 Metadata，保持 v1 请求和旧客户端兼容
- [x] 补齐交易四指标口径并接入 YAML Context Resolver
- [x] 增加稳定回退原因分类和真实 DeepSeek Smoke 输出
- [x] 在 Streamlit 添加默认折叠技术详情，保留全部稳定性修复
- [x] 完成75项自动化、60次API循环和50次真实浏览器循环
- [x] 验证第三问由 DeepSeek 完成且不回退
- [x] 更新 Sprint 文档和页面截图
- **状态：** complete

### 阶段 12：Sprint 5 Product Demo 重构
- [x] 隐藏 Streamlit 开发工具栏、菜单、主题、打印和录屏入口
- [x] 重构品牌、业务导航、经营概览和智能问数首页
- [x] 从只读 Demo 数据库加载四项经营概览指标
- [x] 增加可扩展的六个推荐问题
- [x] 调整结果为业务结论、关键指标、表格、SQL、技术详情顺序
- [x] 统一页面中文产品语言和结果字段映射
- [x] 保留 Metadata、DeepSeek、Hybrid、安全层和稳定性修复
- [x] 完成桌面、真实结果和移动端浏览器验收
- [x] 增加前端产品契约与 KPI 数据测试
- **状态：** complete

### 阶段 13：Sprint 5.1 场景选择器与 Sprint 5.2 Rule First Hybrid
- [x] 将六个业务模块改为可交互场景选择器
- [x] 动态切换场景说明、输入提示和推荐问题
- [x] 为未开放模块提供明确产品提示
- [x] 将 Hybrid 调整为 Rule First、LLM Extension
- [x] 三个标准问题命中 Rule 时不调用 DeepSeek
- [x] Rule 未命中后调用 LLM，LLM 失败不再回退 Rule
- [x] Metadata 增加 `rule_matched`、`route` 和 `failure_reason`
- [x] 完成87项自动化测试与 Rule/LLM 真实路由验证
- **状态：** complete

### 阶段 14：GitHub 发布整理
- [x] 读取发布指令并审计现有目录、Git 状态和 GitHub 工具
- [x] 初步扫描密钥、个人信息、绝对路径和演示数据库
- [x] 将赛事附件、会议材料、Prompt 和本地输出移入 `archive_local/`
- [x] 完善 `.gitignore`，确保 `.env`、环境、缓存、归档和个人文件不入库
- [x] 整理发布版 README，并新增 CONTRIBUTING 与 SECURITY
- [x] 修正文档中的当前阶段、Rule First Hybrid 和测试数量
- [x] 完成编译、测试、数据库、TestClient API 和隐私验证
- [x] 初始化 Git 主分支并创建本地首个提交
- [x] 安装并授权 GitHub CLI，创建仓库并推送（后续按用户要求设为公开）
- **状态：** complete

### 阶段 15：全仓库一致性审计与历史文件清理
- [x] 以当前代码、配置、数据库和测试核对有效架构事实
- [x] 逐份分类正式文档、历史记录、重复内容和失效文件
- [x] 更新接口契约、数据库指标字典、项目方案和 README
- [x] 清理确认无引用且无历史价值的旧代码、脚本、截图和计划
- [x] 新增 `docs/仓库一致性审计报告.md` 并记录全部取舍
- [x] 完成依赖、编译、测试、数据库、API、前端、链接和隐私验证
- [x] 创建独立 Git 提交，同步桌面项目并推送 GitHub
- **状态：** complete

### 阶段 16：团队协作框架与首轮任务落地
- [x] 在独立 `chore/team-workflow` 分支实施，不直接修改 `main`
- [x] 定义六人角色、职责边界、目录所有权和交叉审核关系
- [x] 拆分六项首轮任务、交付物、依赖和验收标准
- [x] 新增四类 Issue 表单、PR 模板和精确范围 CODEOWNERS
- [x] 更新 CONTRIBUTING、README、CHANGELOG 和协作阶段记录
- [x] 验证 GitHub 模板、Markdown 链接、CODEOWNERS 路径和87项全量回归
- [x] 创建六个 GitHub Issues并核对标签与内容
- [ ] 推送分支并创建 Pull Request
- [ ] 同步桌面副本并复核远端状态
- **状态：** in_progress

## 关键问题
1. 如何避免项目沦为“套壳大模型生成 SQL”？
2. 如何让模拟数据既不泄露隐私，又足以支撑真实银行经营分析逻辑？
3. 如何让答辩演示同时体现数据分析能力、产品思维和 AI 工程可靠性？

## 已做决策
| 决策 | 理由 |
|------|------|
| 项目暂定名 BankInsight | 简洁、可用于作品集，也准确表达银行洞察场景 |
| 数据库首版使用 SQLite，生产映射 PostgreSQL/MySQL | 便于本地演示，同时保留真实数据库迁移路径 |
| 先做指标语义层，再做 NL2SQL | 指标口径是项目区别于普通 Text-to-SQL Demo 的核心 |
| 默认只读、查询限行、超时与成本预算 | 银行场景必须把安全治理设计为主流程而非附加功能 |

## 遇到的错误
| 错误 | 尝试次数 | 解决方案 |
|------|---------|---------|
| 沙箱内 pip 无法解析公网域名 | 1 | 经授权在临时虚拟环境联网安装，成功 |
| 沙箱内 Uvicorn 无法绑定本地端口 | 1 | 经授权启动临时本地服务，成功 |
| `/api/v1/ask` 返回 HTTP 500 | 1 | 已定位为占位 Provider 主动抛错；本阶段只记录，第二阶段实现 |

## 下一阶段
- 先完成团队协作框架 PR 和六个首轮 Issue，再由项目负责人把 Issue 分配给具体成员；本轮不开发新业务功能。
