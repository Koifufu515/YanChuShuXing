# Issue #6 官方题库批量评测与版本回归框架 设计文档

> 日期：2026-07-18
> 对应 Issue：#6 官方题库批量评测、错误归因与版本回归验收
> 分支：`test/official-evaluation-framework`
> 状态：设计已确认，待实现

## 1. 目标与范围

按 `docs/06_系统测试与版本评测.md` 落地四项交付物：

1. 官方题库批量评测程序；
2. 结果标准化与自动判分规则；
3. 固定专项测试用例库；
4. 版本基线保存与回归对比报告。

本轮做到"框架完整 + 真题就绪"：正式五表数据库（Issue #4）与语义资产（Issue #5）尚未完成，
评测框架先行（task_plan 阶段 6 允许），首次基线在 Demo 库上以 hybrid 模式运行，
失败分布本身即为基线；正式库接入后用同一框架重跑。

**非目标**：不做第二套人工查询判分依据；不做评测网页；不引入 pytest 或新框架。

## 2. 调用方式（已定：方案 A）

评测 Runner 通过 HTTP 调用真实后端 `/api/v1/query`（复用 `frontend/api_client.py`
的 `BankInsightClient`，先例见 `scripts/stability_check.py`）。理由：

- 符合评测规范"将问题作为真实用户输入提交给后端查询接口"；
- API 响应 `metadata` 已含 `configured_mode / executed_generator / rule_matched /
  route / semantic / llm_latency_ms / fallback`，加上 `sql`、`error.code`，
  归因所需字段零后端改动（已用真题冒烟验证）；
- API 层序列化与错误结构同时被覆盖。

## 3. 目录结构与公开/受控边界

```text
evaluation/                        # 公开：纯框架代码，零真题内容
├── __init__.py
├── models.py                      # EvalQuestion / EvalRecord / RunSummary 等 dataclass
├── question_bank.py               # 从受控 JSONL 加载题库，解析题号 分区-难度-序号
├── runner.py                      # 逐题调后端，落全链路记录，断点续跑
├── normalization.py               # 答案标准化（含 RULES_VERSION 常量）
├── scoring.py                     # 按题型判分（含 RULES_VERSION 常量）
├── attribution.py                 # error.code → 失败阶段 → 交接对象
├── reporting.py                   # 汇总指标、受控完整报告、脱敏公开摘要
└── compare.py                     # 两个 run 对比：改善/退化/耗时变化

scripts/
├── extract_question_bank.py       # 官方 xlsx → data/private/evaluation/questions.jsonl
│                                  #（--source 路径参数化，禁止硬编码本机路径）
└── run_evaluation.py              # CLI：跑评测 / 对比版本

tests/evaluation/                  # unittest；只用合成样例（虚构机构与题目）
├── test_question_bank.py
├── test_normalization.py
├── test_scoring.py
├── test_attribution.py
└── test_special_cases.py          # 交付物 3：专项用例库

data/private/evaluation/           # git-ignored 受控资产
├── questions.jsonl                # 200 题：编号/分区/难度/题面/官方答案
├── runs/<run_id>/details.jsonl    # 逐题全链路记录（追加写）
├── runs/<run_id>/summary.json     # 聚合指标
└── baselines/<name>.json          # 版本基线
```

安全边界：

- 官方题面、答案、逐题 SQL、逐题结果只存在于 `data/private/evaluation/`（已在 `.gitignore`）；
- 公开聚合报告不自动写入仓库：`reporting.py` 把脱敏摘要生成到受控目录，人工审核后才拷入 `docs/`；
- 测试分区内容不进入 Rule、Prompt、Few-shot、推荐问题或任何公开文件；
- 本设计文档与全部框架代码、单测不得出现任何真题题面或答案。

新增 dev 依赖：`openpyxl`（仅提取脚本使用，加入 `backend/requirements-dev.txt`）。

## 4. 数据流与运行方式

```text
官方 xlsx --extract_question_bank--> questions.jsonl
uvicorn 起后端 --> run_evaluation.py --partition train --run-id <id> [--limit N] [--ids ...]
  每题记录：题号/分区/难度、configured_mode、executed_generator、rule_matched、
  route、semantic、sql、error.code/message、columns/rows/summary、
  端到端耗时、llm_latency_ms、git commit、模型名、数据库标签、规则版本
  --> runs/<run_id>/details.jsonl + summary.json
```

- 题号解析：`TRAIN|VAL|TST`-`S|M|H`-`NN` → 分区 + 难度；
- 默认只跑 `train`；`val`/`test` 必须显式传参（分区隔离）；
- **冒烟能力**：`--limit N` 与 `--ids <题号列表>` 支持先 5 题小跑再全量；
- **断点续跑**：details.jsonl 追加写，重跑跳过已完成题号
  （实测 LLM 路由单题约 5 秒，120 题约 11 分钟，中断可恢复）；
- 首次基线：Demo 库 + hybrid 跑 train 120 题，预期大面积失败，失败分布即基线。

## 5. 标准化与判分

- **标准化**（`normalization.py`）：金额单位（元/万元/亿元）、百分比与百分点区分、
  小数精度与舍入、日期表达等价类（`2025-12-31` / `2025年12月末` 等）、
  机构名标准化、空值/无数据/零值区分；
- **判分**（`scoring.py`）按题型：
  - 单值题：数值 + 单位，容差可配置且版本化；
  - 排名/前 N 题：机构集合 + 名次 + 并列关系;
  - 多值列表题：关键字段全部核对；
  - 综合题：官方答案关键要素覆盖检查；
- 系统答案与官方答案**双方都先标准化再比较**；
- **诚实兜底**：官方答案为自然语言，无法可靠解析的题标记 `needs_manual_review`，
  不假装判分，防止宽松比对虚增准确率；
- **异常题**：读取 05 号题库异常清单（`docs/business_semantics/题库异常清单.csv`
  的私有完整版），按项目负责人结论标记并单列统计；
- `RULES_VERSION` 写入每次 run 记录。

## 6. 第一层归因

`attribution.py` 按 `error.code` 自动映射（映射表已对照 `backend/app/application/errors.py`）：

| error.code | 失败阶段 | 交接对象 |
|---|---|---|
| UNSUPPORTED_QUESTION / CLARIFICATION_REQUIRED / INVALID_SEMANTIC_OUTPUT / UNSUPPORTED_METRIC | 语义理解 | 05 号复核口径，技术实现交项目负责人 |
| INVALID_SQL_OUTPUT | SQL 生成 | 生成模块开发成员 |
| LLM_TIMEOUT / LLM_UNAVAILABLE / LLM_PROVIDER_ERROR | 模型可用性 | 项目负责人 |
| SQL_REJECTED（`sqlglot_checker.py` 唯一拒绝码，细分原因取 error.message） | 安全层 | 安全模块开发成员 |
| QUERY_EXECUTION_ERROR / QUERY_TIMEOUT / DATABASE_UNAVAILABLE | 数据库执行 | 04 号数据负责人 |
| 无 error 但判分不通过 | result_mismatch（人工复核队列） | 06 号按证据二次分派 |
| 题号命中异常清单 | 官方题库异常 | 05 号复核，项目负责人定策略 |

冒烟验证已确认 `result_mismatch` 路径真实存在：真题在 Demo 库上可
"无错误执行但返回 null"。

## 7. 专项用例与版本回归

- **专项用例库**（`tests/evaluation/test_special_cases.py`，独立于官方数据，可进公开 CI）：
  空问题、不存在机构、超范围日期、危险 SQL（DROP/UPDATE/多语句）、超时、
  无数据、错误响应不泄漏内部异常；
- **版本回归**（`compare.py`）：两个 run 的 details 对比，输出：
  上版错本版对清单、退化清单、新增失败、按分区/难度/路由的准确率变化、
  P50/P95 耗时变化 → 受控 diff 报告 + 脱敏摘要。

## 8. 测试策略与工作流

- 框架单测全部用合成数据（虚构"测试银行"类机构名），runner 单测用 mock client 不联网，
  unittest 风格与现有 `tests/` 一致；
- 提交前跑仓库全套验证：`pip check` → `compileall` → `unittest discover` → `stability_check`；
- PR 标题：`test: 建立官方题库批量评测与版本回归框架`。

## 9. 依赖与风险

| 项 | 说明 |
|---|---|
| 依赖 `fix/windows-sqlite-connection-close` | 环境验证发现 3 处 `with sqlite3.connect` 未关闭连接（Windows 文件锁下 init_db 无法替换 DB、测试临时目录无法清理），已单独成 fix 分支，建议先行合并 |
| Python 版本 | 本机 3.13.5（项目验证环境 3.10.11），87 项测试全绿，依赖全兼容 |
| 正式库未建 | 首次基线在 Demo 库上跑，answer 全不可比属预期；判分正确性用合成样例单测保证 |
| 判分规则先行风险 | 05 号口径未确认前，normalization 只实现通用规则；口径确认后按同步规则升版 RULES_VERSION |
| 成本 | hybrid 全量 120 题约 240 次 DeepSeek 调用（两阶段），deepseek-v4-flash 成本可忽略 |

## 10. 验收对照

对照 Issue #6 十条验收标准：本轮交付满足 1-3、5-9（框架与规则层面）；
第 4 条（与官方答案直接比较出真实准确率）与第 7 条（有意义的版本基线）
在 Issue #4 正式库接入后用同一框架直接达成；第 10 条（审核合并）由 PR 流程完成。
