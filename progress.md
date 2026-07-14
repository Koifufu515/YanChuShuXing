# 进度日志

## 会话：2026-07-10

### 阶段 1：需求与边界
- **状态：** complete
- 执行的操作：拆解 13 个章节，明确首版交付为方案文档与工程骨架。
- 创建/修改的文件：`task_plan.md`、`findings.md`、`progress.md`。

### 阶段 2：业务与产品设计
- **状态：** complete
- 执行的操作：完成 13 章节完整方案、七大指标主题、15 个场景、题目对比和四周路线。
- 创建/修改的文件：`docs/项目完整方案.md`、`docs/数据库与指标字典.md`、`README.md`。

### 阶段 3：技术与数据框架
- **状态：** complete
- 执行的操作：建立 10 表 DDL、指标与 Schema YAML、问数数据模型、流水线接口、SQL AST 安全校验和 API 路由骨架。
- 创建/修改的文件：`sql/schema.sql`、`config/*.yml`、`backend/`、`frontend/README.md`、`tests/test_schema.py`。

### 阶段 4：验证
- **状态：** complete（运行时依赖测试转入下一阶段）
- 执行的操作：执行 SQLite 建表与约束测试；编译全部 Python 文件；使用 Ruby YAML 解析器检查配置；逐项核对需求覆盖数量。
- 说明：当前环境尚未安装 FastAPI、Pydantic、SQLGlot、PyYAML 和 Uvicorn，因此本轮未启动 API，也未运行 SQLGlot 安全用例。

## 测试结果
| 测试 | 输入 | 预期结果 | 实际结果 | 状态 |
|------|------|---------|---------|------|
| 目录隔离 | 当前工作区 | 新项目不影响已有项目 | `bankinsight_nl2sql/` 独立创建 | 通过 |
| SQLite DDL | 10 张表 | 全部建表成功 | 3 项单元测试通过 | 通过 |
| Python 语法 | 5 个后端模块 | 编译无错误 | `py_compile` 退出码 0 | 通过 |
| YAML 配置 | metrics/schema | 可解析 | Ruby YAML 解析成功 | 通过 |
| 需求覆盖 | 13 项要求 | 数量与结构完整 | 全部检查项 PASS | 通过 |

## 错误日志
| 时间戳 | 错误 | 尝试次数 | 解决方案 |
|--------|------|---------|---------|
| - | 暂无 | 0 | - |

## 五问重启检查
| 问题 | 答案 |
|------|------|
| 我在哪里？ | 初始框架已交付 |
| 我要去哪里？ | 下一阶段生成数据、Gold SQL 和前三个端到端接口 |
| 目标是什么？ | 完成可开发、可演示、可写简历的智能问数项目初始框架 |
| 我学到了什么？ | 见 `findings.md` |
| 我做了什么？ | 已完成方案、数据模型、指标语义层、后端模块契约与基础验证 |

## 会话：2026-07-12

### 阶段 6：工程审计与接口冻结
- **状态：** in_progress
- 执行的操作：恢复既有计划；逐个读取后端、配置、DDL、测试和前端目录；对比桌面与工作区核心文件哈希。
- 范围限制：只产出工程审计、接口契约和运行证据；不实现 LLM、数据库执行器、网页或新 Pipeline。
- 初步结论：DDL 和安全检查有真实逻辑；后端只有可导入骨架，查询接口依赖注入明确未配置；无 LLM、数据库执行器和网页。
- 运行证据：全局环境缺依赖；临时隔离环境依赖安装成功；FastAPI `/health` 为 200，`/api/v1/ask` 为 500，失败点为未配置 Pipeline Provider。
- 数据与测试：DDL 建立 10 表/14 索引且外键检查通过；现有 3 项测试通过。
- 新增文档：`docs/工程审计与原型实施计划.md`、`docs/接口契约.md`。
- 文档核对：审计要求与六类接口均覆盖；核心代码、配置、DDL 和测试文件与桌面副本哈希一致，未改业务代码。
- 同步结果：两份新文档与 `task_plan.md`、`findings.md`、`progress.md` 已同步到桌面 `农行杯金融科技` 目录；阶段 6 完成，等待用户确认。

## 错误日志（2026-07-12）
| 错误 | 结果 |
|---|---|
| 沙箱内 pip 网络解析失败 | 经授权在 `/tmp` 隔离环境安装成功 |
| 沙箱内 Uvicorn 绑定端口被拒 | 经授权启动成功，确认属于环境限制 |
| 查询接口 HTTP 500 | 定位到 `get_query_pipeline()` 占位异常，未在本阶段修复 |
| Sprint 3 最终 Uvicorn 复跑被授权额度限制拒绝 | 保留首轮真实 HTTP 证据；修复后以 TestClient 和静态依赖检查验证，未绕过限制 |

## 会话：2026-07-12 Sprint 3

### 阶段 7：架构实施与最小纵向原型
- **状态：** complete
- 已确认：外部 HTTP API 使用 v1；内部使用 Architecture Review v2；SQLGenerator 与 LLMProvider 分离。
- 执行策略：按纵向 TDD 切片实施，先固定问题真实查询，再补拒绝与错误路径。
- 范围限制：不接真实 LLM、不做网页、RAG、向量检索、Agent、Docker 或完整权限审计。
- 实施计划：`docs/superpowers/plans/2026-07-12-sprint3-minimal-vertical-prototype.md`。
- TDD 切片 1：架构契约测试先因 `app.application` 不存在失败；补充纯 dataclass、统一异常和7个独立 Ports 后通过。应用模型不依赖 FastAPI、Pydantic、SQLite、SQLGlot 或具体 Adapter。
- TDD 切片 2：数据库初始化测试先因模块不存在失败；实现原子替换和固定小样本后通过，重复初始化不会累加数据。
- TDD 切片 3：Executor 的参数化、限行、错误和只读测试先失败；实现只读 SQLite URI、`max_rows + 1`、类型转换与统一异常后3项通过。
- TDD 切片 4：YAML Resolver 与 Rule Generator 先因模块不存在失败；实现关键词上下文和3条参数化规则后4项通过。
- TDD 切片 5：SQLGlot Adapter 的合法/危险/未知表/敏感列测试先失败；复用原 Validator 并完成纯模型转换后3项通过。
- TDD 切片 6：模板摘要和 NoOp Audit 测试先失败；实现基于结果列的3类摘要、空结果与截断提示后3项通过。
- TDD 切片 7：Pipeline 测试先因模块不存在失败；实现仅依赖 Ports 的编排、短路、异常归一化与4类审计事件后4项通过。旧 `services/pipeline.py` 改为兼容导入。
- TDD 切片 8：API 测试先暴露当前 Starlette 需要 `httpx2`，再因 Composition Root 缺失失败；补充独立开发依赖、唯一组装入口、API DTO 和错误处理后，三问、400、403、500、503、422及 `/ask` 兼容路径均通过。
- 项目数据库：连续初始化两次后仍为客户3、账户4、交易4，外键违规0。
- 全量验证：29项测试通过，Python 编译通过，依赖检查无破损。
- 真实 HTTP：Uvicorn 启动成功，`/health` 为200，三条 `/api/v1/query` 均为200并返回真实数据库结果。
- 文档：README 已补快速启动；新增 `docs/Sprint3_架构实施与最小原型记录.md`。
- 两轴首轮审查：发现异常边界、依赖方向、空白校验、真实超时、安全消息和规则范围问题；已逐项修复并增加回归测试。
- 修复后验证：35项测试通过，Application/Ports 依赖方向和 API 注入方向静态检查通过。
- 最终 Uvicorn 复验：本机授权额度限制拒绝新的端口启动请求；未尝试绕过。首轮真实 HTTP 已通过，修复后使用 TestClient 覆盖。
- 最终环境：macOS（Apple Silicon）、Python 3.10.11、项目根目录 `.venv`；依赖按 `backend/requirements-dev.txt` 安装，`pip check` 无破损依赖。
- 最终验证：重新初始化确定性数据库后，35项测试通过；Python 编译、Application/Ports 依赖方向、3/4/4条演示数据计数和外键检查均通过。
- 独立复核说明：首轮双轴审查已完成并修复6类问题；修复后的第二轮代理复核因 Codex 使用额度中断，最终由主工程师按相同标准复核并以回归测试和静态检查收口。

## 会话：2026-07-12 Sprint 4.1

### 阶段 8：产品化 Demo
- **状态：** complete
- 新增 `frontend/api_client.py`：只调用 `/api/v1/query`，结构化处理成功、HTTP业务错误和连接失败。
- 新增 `frontend/app.py`：实现示例问题、加载状态、SQL、表格、业务解释、Warning、Error 和运行信息。
- 前端客户端3项测试通过；真实浏览器已验证三个固定问题和不支持问题。
- 浏览器检查发现并修复示例切换保留旧结果、Streamlit弃用参数和运行信息截断问题。
- 已生成桌面与移动端截图；最终截图使用账户余额真实接口结果。
- 展示层新增 Warning 和 Error 行为测试；Sprint 3 回归与 Sprint 4.1 新测试合计40项全部通过。
- 最终运行信息改为响应式网格，桌面和390像素窄屏均完整显示，无文字溢出。
- 已同步桌面 `农行杯金融科技` 目录，README、CHANGELOG、Sprint 4.1文档、截图和前端核心文件哈希一致。

## 会话：2026-07-12 Sprint 4.2

### 阶段 9：DeepSeek 与 Hybrid Generator
- **状态：** complete
- 新增统一 Settings、`.env.example` 和 `.gitignore`，真实密钥只从本地环境读取。
- 新增 DeepSeek Provider、两阶段 LLMSQLGenerator 和 HybridSQLGenerator；Pipeline 保持不变。
- Fake Provider 核心测试和三模式 API 兼容测试已通过；危险 LLM SQL 被原有 Safety 拒绝。
- 真实 Smoke：有效客户数和账户余额由 DeepSeek两阶段成功；交易汇总因指标上下文不足回退规则，三问结果均正确。
- 真实调用修复本机 CA 证书问题；20秒曾瞬时超时，60秒 Smoke 完成。
- 最终 Smoke 复验：有效客户数 DeepSeek 约1.85秒，返回“当前有效客户数量为2户”；账户余额 DeepSeek 约2.25秒，返回“客户C001当前有效账户余额合计为600.00万元”；交易汇总回退规则并返回3笔、流入10万、流出5万、净流入5万。
- 最终自动化：61项测试通过，Python编译、依赖、Pipeline/Ports边界、前端边界、`.env`忽略和本地密钥扫描均通过。
- 桌面同步完成：关键源码与文档哈希一致，本地 `.env` 保留且密钥未出现在其他交付文件中。

## 会话：2026-07-13 Streamlit 稳定性专项

### 阶段 10：Segmentation Fault 定位与修复
- **状态：** complete
- 暂停 Sprint 4.3，仅排查进程级崩溃；未修改 Pipeline、数据库、生成器或业务问题。
- 新建项目根目录独立 `.venv`，不再引用其他工程的虚拟环境。
- 检查6份 macOS Crash Report，均为 `EXC_BAD_ACCESS / SIGSEGV`，触发栈集中在 PyArrow 的 Mimalloc 分配与 Arrow 表格序列化路径。
- 修复：在 Streamlit 导入前设置 `ARROW_DEFAULT_MEMORY_POOL=system`；结果表格改为转义后的轻量 HTML；Session State 只保存普通字典、列表和标量；固定前端关键依赖版本。
- 新增前端状态、连续查询、失败恢复、Hybrid 超时恢复测试和稳定性脚本。
- 全量回归：69项测试通过，`pip check` 与 Python 编译通过，Arrow 默认内存池确认为 `system`。
- 真实浏览器：20次双问题交替查询与30次三问题循环均通过；不支持问题后可继续查询；后端断开时网页显示结构化错误且 Streamlit 进程保持运行。
- API 稳定性脚本：三个固定问题循环60次，逐次返回真实结果，全部通过。
- 修复后未产生新的 macOS Python Crash Report。

## 会话：2026-07-13 Sprint 4.3

### 阶段 11：查询链路可解释性与交易语义补齐
- **状态：** complete
- 新增框架无关的 QueryMetadata、SemanticMetadata 和 FallbackMetadata，由 Generator 产生并经 GeneratedSQL、QueryOutcome、API DTO 透传；Pipeline 不识别模式或模型。
- Rule 返回最小 Metadata；LLM 返回模型、两阶段总耗时和已验证语义；Hybrid 成功保留 LLM Metadata，回退记录稳定原因及实际 Rule Generator。
- 新增 `INVALID_SEMANTIC_OUTPUT`、`INVALID_SQL_OUTPUT`、`CLARIFICATION_REQUIRED`、`UNSUPPORTED_METRIC` 等稳定分类，不暴露第三方原始错误。
- 在 `config/metrics.yml` 增加 transaction_count、transaction_inflow、transaction_outflow、net_transaction_flow，并由 Resolver 为交易汇总召回四项指标与真实交易表字段。
- Streamlit 新增默认折叠“技术详情”，同时保留 Arrow 系统内存池、HTML表格和纯数据 Session State。
- 真实 DeepSeek：三问均由 LLM 完成；交易问题最终识别为 `monthly_transaction_summary / transaction`，四项指标完整，SQL通过Safety，结果为3笔、流入10万、流出5万、净流入5万，未回退。
- 自动化：75项测试通过，`pip check` 与 Python 编译通过；60次API稳定性脚本通过。
- 浏览器：技术详情真实展示通过；20次双问题交替、30次三问题循环逐次核对新Request ID与结果；不支持问题后恢复成功。
- 稳定性：后端与前端保持运行，未产生新的 macOS Python Crash Report。

## 会话：2026-07-13 Sprint 5

### 阶段 12：Product Demo 重构
- **状态：** complete
- 范围严格限定为 Streamlit 前端；未修改 Pipeline、Generator、Safety、数据库结构或 API 行为。
- 首页重构为品牌、业务模块导航、经营概览、智能问数和推荐问题五层结构。
- 新增只读 `frontend/kpi_repository.py`，从 Demo SQLite 实时读取有效客户、账户、交易和理财产品数量，不硬编码展示值。
- 推荐问题由数据结构驱动，当前展示6项；前三项点击后规范化为已有后端支持问法，后三项保留为后续产品扩展入口。
- 查询结果顺序调整为业务结论、关键指标、查询结果、生成 SQL、技术详情；表格列名和金额单位中文化。
- 技术详情将运行模式、实际执行器、模型、语义和指标映射为中文，同时保留原 Metadata 能力。
- 使用 `.streamlit/config.toml` 的 `toolbarMode=minimal`、`showErrorDetails=none`，并以CSS隐藏页头、工具栏、菜单和页脚。
- 桌面与390像素窄屏均无横向溢出；Deploy和主菜单均未出现在浏览器页面。
- 保留 `ARROW_DEFAULT_MEMORY_POOL=system`、无 `st.dataframe`、Session State只存普通数据。
- 新增首页、真实查询结果和移动端截图；真实账户余额查询的页面顺序与中文列名验证通过。

## 会话：2026-07-14 Sprint 5.1 与 Sprint 5.2

### 阶段 13：场景选择器与 Rule First Hybrid
- 六个业务模块已改为同页卡片式场景选择器；默认经营分析，切换时同步更新说明、Placeholder、推荐问题与待开放提示。
- Hybrid 从“LLM 优先、Rule 回退”改为“Rule First、LLM Extension”；路由封装在 `HybridSQLGenerator`，Pipeline 不包含固定问题判断。
- 标准三问均命中 Rule 且不调用 DeepSeek；非规则同义问法进入 LLM 并成功返回真实数据库结果。
- Metadata 新增 `rule_matched`、`route` 和 `failure_reason`；安全拒绝、缺少参数、未支持指标和模型异常均有稳定分类。
- 全量87项自动化测试通过；FastAPI 和 Streamlit 均完成真实启动验证。

## 会话：2026-07-14 GitHub 发布整理

### 阶段 14：仓库审计与发布准备
- **状态：** in_progress
- 当前目录尚未初始化 Git，未配置 remote；系统原先未安装 GitHub CLI。
- 根目录包含赛事附件、报名表、会议 PDF、Prompt 文档、Office 临时文件和本地 Playwright 输出，不适合直接提交，将移入被忽略的 `archive_local/`。
- `.env` 含本地模型配置，保留在电脑且不得提交；`.env.example` 使用空密钥占位。
- 文本密钥扫描未在正式代码与文档中发现真实 API Key、访问令牌、邮箱、身份证号或手机号。
- 绝对路径仅出现在历史进度、稳定性排查文档和本次发布指令中；发布版已改为相对说明并归档指令文件。
- `data/processed/bankinsight.db` 为 152KB 确定性模拟数据库，仅含 C001/C002/C003 等虚构编号和统计属性，没有姓名、手机号或身份证字段，适合提交。
- GitHub CLI 安装首轮卡在 Homebrew 自动更新，终止后跳过更新重试仍无输出；后续改用官方发行包或其他安全安装方式。
- 已从 GitHub 官方发行包安装 GitHub CLI 2.96.0（arm64），并完成浏览器设备授权。
- 发布副本位于 `BankInsight/`，只复制正式代码、配置、测试、文档、演示截图和确定性模拟数据库，桌面原始项目未被覆盖。
- 干净环境复验确认 FastAPI 0.139 的 TestClient 依赖 `httpx2>=2.5,<3.0`；旧 `httpx` 虽可运行但会产生弃用警告，因此保留项目原有 `httpx2` 声明。
- 发布副本完成 Python 编译、数据库重复初始化、外键检查和87项自动化测试，全部通过；TestClient 已覆盖 `/health`、三条标准查询和结构化错误。
- 演示数据库复核为3名虚构客户、4个账户、4笔交易、0个产品，仅含 C001 等模拟编号，无姓名、手机号、身份证或真实银行数据。
- 文本扫描未发现真实密钥、绝对用户路径、手机号或身份证号；仅 `.env.example` 占位符和测试用 `local-secret` 命中关键字扫描。
- 当前沙箱禁止监听本机新端口，因此本轮未重复启动 Uvicorn/Streamlit；此前真实启动与浏览器验收记录保留，当前代码以完整 TestClient 和前端契约测试复验。
- 发布副本已创建独立 `.venv` 并按仓库依赖文件完成安装；`pip check`、Python 编译、数据库初始化和87项测试均在该环境通过。
- GitHub CLI 2.96.0 已通过设备授权登录 `Koifufu515`，仓库提交身份使用 GitHub noreply 地址。
- 已创建私有仓库 `https://github.com/Koifufu515/BankInsight`，并将 `main` 分支推送到 `origin/main`。
- 首个提交为 `f3bda09 chore: prepare BankInsight repository for team collaboration`；远端未包含 `.env`、虚拟环境、本地归档或赛事附件。
