# evaluation/ 官方题库批量评测框架

Issue #6 交付物。公开仓库只含框架代码与合成测试样例；官方题面、答案、
逐题 SQL 与逐题结果一律位于 git 忽略的 `data/private/evaluation/`。

## 使用流程（Windows PowerShell）

```powershell
$env:PYTHONPATH = "backend;."

# 1. 提取受控题库（官方 xlsx 在仓库外，路径参数化）
.venv\Scripts\python.exe scripts\extract_question_bank.py --source <官方xlsx路径>

# 2. 起后端（另开终端）
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 冒烟 5 题
.venv\Scripts\python.exe scripts\run_evaluation.py run --run-id smoke-01 --partition train --limit 5

# 4. 全量训练分区
.venv\Scripts\python.exe scripts\run_evaluation.py run --run-id baseline-01 --partition train

# 5. 版本对比
.venv\Scripts\python.exe scripts\run_evaluation.py compare --old baseline-01 --new baseline-02
```

## 模块

| 模块 | 职责 |
|---|---|
| `question_bank.py` | 受控题库加载与题号（分区/难度）解析 |
| `runner.py` | 逐题调用后端 API，断点续跑，逐题落盘 |
| `normalization.py` / `scoring.py` | 标准化与判分，`RULES_VERSION` 版本化；无法可靠解析的官方答案标记 `NEEDS_MANUAL_REVIEW`，不虚增准确率 |
| `attribution.py` | error.code → 失败阶段 → 交接对象（第一层归因） |
| `reporting.py` | 聚合指标；脱敏公开摘要需人工审核后才可移入 docs/ |
| `compare.py` | 两个 run 的改善/退化/新增错误/耗时对比 |

## 分区纪律

默认只跑训练分区；`--partition val|test` 必须显式指定，测试分区结果
不得进入 Rule、Prompt、推荐问题或公开报告。
