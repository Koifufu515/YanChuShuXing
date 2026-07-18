# Issue #6 官方题库批量评测框架 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 Issue #6 四项交付物：官方题库批量评测程序、结果标准化与自动判分规则、固定专项测试用例库、版本基线与回归对比。

**Architecture:** 新增独立顶层包 `evaluation/`（不 import `app.*`/`frontend.*`，纯标准库 + dataclass），Runner 通过依赖注入的 HTTP client（`frontend/api_client.py` 的 `BankInsightClient`，由 `scripts/run_evaluation.py` 组装）调用真实后端 `/api/v1/query`。受控资产（题库/逐题结果）只落 git-ignored `data/private/evaluation/`。

**Tech Stack:** Python 3.13（本机 venv）、unittest（不是 pytest）、openpyxl（仅提取脚本）、现有 FastAPI TestClient 模式（专项用例）。

**Spec:** `docs/superpowers/specs/2026-07-18-official-evaluation-framework-design.md`

---

## 环境与全局约定（每个 Task 都适用）

- 工作目录：`F:\1\Code\LearningProjects\FITC\BankInsight`，分支 `test/official-evaluation-framework`
- 所有命令前先设：`$env:PYTHONPATH = "backend;."`
- Python 一律用 `.venv\Scripts\python.exe`
- 测试文件平铺在 `tests/`（命名 `test_evaluation_*.py`），与现有结构一致；**不建 `tests/evaluation/` 子目录**（会与顶层 `evaluation/` 包发生 unittest discover 导入名冲突；docs/06 允许按现有测试结构微调）
- **安全红线：任何代码、测试、fixture、commit 不得包含官方题面、官方答案或真实机构名。合成测试数据一律用虚构名（如"测试省甲市农商行"）**
- commit 前缀用 `test:`（评测框架）/ `chore:`（依赖）
- 官方 xlsx 位于仓库外：`F:\1\Code\LearningProjects\FITC\基于大模型与NL2SQL的银行业智能问数系统构建与应用_数据集.xlsx`，其工作表 `问题答案清单` 表头为 `问题编号|问题类型|问题难度|问题描述|问题结果`，题号形如 `TRAIN-S-01`/`VAL-S-02`/`TST-H-12`，分区数 120/40/40

---

### Task 1: 分支准备与依赖

**Files:**
- Modify: `backend/requirements-dev.txt`

- [ ] **Step 1: 合并 Windows sqlite 修复（本任务的测试依赖它）**

```powershell
git merge fix/windows-sqlite-connection-close --no-edit
```

Expected: `Merge made by ...` 或 `Already up to date.`（若该 fix 已先行合入 main 并同步）。
备注：PR 提交前若 fix 分支已合入 main，`git merge origin/main` 后这些提交自然去重。

- [ ] **Step 2: 添加 openpyxl 依赖**

`backend/requirements-dev.txt` 改为：

```text
-r requirements.txt
httpx2>=2.5,<3.0
openpyxl>=3.1,<4.0
```

- [ ] **Step 3: 安装并验证**

```powershell
.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt --disable-pip-version-check
.venv\Scripts\python.exe -m pip check
```

Expected: `No broken requirements found.`

- [ ] **Step 4: Commit**

```powershell
git add backend/requirements-dev.txt
git commit -m "chore: 添加 openpyxl 依赖用于官方题库提取"
```

---

### Task 2: evaluation/models.py — 数据模型与 JSONL 往返

**Files:**
- Create: `evaluation/__init__.py`（空文件）
- Create: `evaluation/models.py`
- Test: `tests/test_evaluation_models.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_models.py`：

```python
import unittest

from evaluation.models import (
    SCORE_NEEDS_MANUAL_REVIEW,
    EvalQuestion,
    EvalRecord,
)


class EvalModelTest(unittest.TestCase):
    def test_record_json_line_round_trip_preserves_chinese_and_none(self) -> None:
        record = EvalRecord(
            question_id="TRAIN-S-01",
            partition="TRAIN",
            difficulty="S",
            question_type="单值查询",
            run_id="run-demo-1",
            started_at="2026-07-18T10:00:00",
            sql=None,
            error_code="UNSUPPORTED_QUESTION",
            error_message="暂不支持该问题。",
            summary=None,
            rows=[["测试省甲市农商行", 1.23]],
            total_row_count=1,
        )
        line = record.to_json_line()
        self.assertNotIn("\n", line)
        self.assertIn("测试省甲市农商行", line)
        restored = EvalRecord.from_json_line(line)
        self.assertEqual(restored, record)

    def test_record_defaults(self) -> None:
        record = EvalRecord(
            question_id="VAL-M-02",
            partition="VAL",
            difficulty="M",
            question_type="排名",
            run_id="r",
            started_at="t",
        )
        self.assertEqual(record.score_status, SCORE_NEEDS_MANUAL_REVIEW)
        self.assertEqual(record.rows, [])
        self.assertIsNone(record.sql)

    def test_question_is_frozen(self) -> None:
        question = EvalQuestion(
            question_id="TST-H-01",
            partition="TST",
            difficulty="H",
            question_type="综合",
            question_text="合成题面",
            official_answer="合成答案",
        )
        with self.assertRaises(Exception):
            question.question_id = "X"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
$env:PYTHONPATH = "backend;."
.venv\Scripts\python.exe -m unittest tests.test_evaluation_models -v
```

Expected: `ModuleNotFoundError: No module named 'evaluation'`

- [ ] **Step 3: 实现**

`evaluation/__init__.py`：空文件。

`evaluation/models.py`：

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCORE_CORRECT = "CORRECT"
SCORE_INCORRECT = "INCORRECT"
SCORE_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
SCORE_EXCLUDED_ANOMALY = "EXCLUDED_ANOMALY"
SCORE_NOT_SCORED_SYSTEM_ERROR = "NOT_SCORED_SYSTEM_ERROR"

SCORE_STATUSES = frozenset(
    {
        SCORE_CORRECT,
        SCORE_INCORRECT,
        SCORE_NEEDS_MANUAL_REVIEW,
        SCORE_EXCLUDED_ANOMALY,
        SCORE_NOT_SCORED_SYSTEM_ERROR,
    }
)


@dataclass(frozen=True)
class EvalQuestion:
    question_id: str
    partition: str
    difficulty: str
    question_type: str
    question_text: str
    official_answer: str


@dataclass
class EvalRecord:
    question_id: str
    partition: str
    difficulty: str
    question_type: str
    run_id: str
    started_at: str
    elapsed_ms: int | None = None
    configured_mode: str | None = None
    executed_generator: str | None = None
    rule_matched: bool | None = None
    route: str | None = None
    semantic: dict[str, Any] | None = None
    sql: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    total_row_count: int = 0
    summary: str | None = None
    llm_latency_ms: float | None = None
    score_status: str = SCORE_NEEDS_MANUAL_REVIEW
    score_reason: str | None = None
    attribution_stage: str | None = None
    attribution_owner: str | None = None
    code_version: str | None = None
    model: str | None = None
    db_label: str | None = None
    rules_version: str | None = None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json_line(cls, line: str) -> "EvalRecord":
        payload = json.loads(line)
        return cls(**payload)
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_models -v
```

Expected: `OK`（3 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/__init__.py evaluation/models.py tests/test_evaluation_models.py
git commit -m "test: 评测框架数据模型与JSONL往返"
```

---

### Task 3: evaluation/question_bank.py — 题号解析与题库加载

**Files:**
- Create: `evaluation/question_bank.py`
- Test: `tests/test_evaluation_question_bank.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_question_bank.py`：

```python
import tempfile
import unittest
from pathlib import Path

from evaluation.models import EvalQuestion
from evaluation.question_bank import (
    load_questions,
    parse_question_id,
    write_questions,
)


def _question(question_id: str, partition: str, difficulty: str) -> EvalQuestion:
    return EvalQuestion(
        question_id=question_id,
        partition=partition,
        difficulty=difficulty,
        question_type="合成类型",
        question_text=f"合成题面{question_id}",
        official_answer=f"合成答案{question_id}",
    )


class ParseQuestionIdTest(unittest.TestCase):
    def test_parses_partition_and_difficulty(self) -> None:
        self.assertEqual(parse_question_id("TRAIN-S-01"), ("TRAIN", "S"))
        self.assertEqual(parse_question_id("VAL-M-40"), ("VAL", "M"))
        self.assertEqual(parse_question_id("TST-H-12"), ("TST", "H"))

    def test_rejects_malformed_ids(self) -> None:
        for bad in ("TRAIN-S", "DEV-S-01", "TRAIN-X-01", "TRAIN-S-AB", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_question_id(bad)


class LoadQuestionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "questions.jsonl"
        write_questions(
            [
                _question("TRAIN-S-01", "TRAIN", "S"),
                _question("TRAIN-M-02", "TRAIN", "M"),
                _question("VAL-S-01", "VAL", "S"),
                _question("TST-H-01", "TST", "H"),
            ],
            self.path,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_loads_all_and_round_trips(self) -> None:
        questions = load_questions(self.path)
        self.assertEqual(len(questions), 4)
        self.assertEqual(questions[0].question_text, "合成题面TRAIN-S-01")

    def test_filters_by_partition_ids_and_limit(self) -> None:
        train_only = load_questions(self.path, partitions={"TRAIN"})
        self.assertEqual([q.question_id for q in train_only], ["TRAIN-S-01", "TRAIN-M-02"])

        picked = load_questions(self.path, ids={"VAL-S-01"})
        self.assertEqual([q.question_id for q in picked], ["VAL-S-01"])

        limited = load_questions(self.path, partitions={"TRAIN"}, limit=1)
        self.assertEqual([q.question_id for q in limited], ["TRAIN-S-01"])

    def test_missing_file_raises_with_hint(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_questions(Path(self.tempdir.name) / "absent.jsonl")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_question_bank -v
```

Expected: `ModuleNotFoundError`/`ImportError`

- [ ] **Step 3: 实现**

`evaluation/question_bank.py`：

```python
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from evaluation.models import EvalQuestion

PARTITIONS = ("TRAIN", "VAL", "TST")
DIFFICULTIES = ("S", "M", "H")


def parse_question_id(question_id: str) -> tuple[str, str]:
    parts = question_id.strip().upper().split("-")
    if (
        len(parts) != 3
        or parts[0] not in PARTITIONS
        or parts[1] not in DIFFICULTIES
        or not parts[2].isdigit()
    ):
        raise ValueError(f"无法解析题号：{question_id!r}，期望格式如 TRAIN-S-01。")
    return parts[0], parts[1]


def write_questions(questions: Iterable[EvalQuestion], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for question in questions:
            handle.write(json.dumps(asdict(question), ensure_ascii=False) + "\n")


def load_questions(
    path: Path,
    partitions: set[str] | None = None,
    ids: set[str] | None = None,
    limit: int | None = None,
) -> list[EvalQuestion]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"题库文件不存在：{path}。请先运行 scripts/extract_question_bank.py 提取受控题库。"
        )
    selected: list[EvalQuestion] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            question = EvalQuestion(**json.loads(line))
            if partitions is not None and question.partition not in partitions:
                continue
            if ids is not None and question.question_id not in ids:
                continue
            selected.append(question)
            if limit is not None and len(selected) >= limit:
                break
    return selected
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_question_bank -v
```

Expected: `OK`（4 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/question_bank.py tests/test_evaluation_question_bank.py
git commit -m "test: 题号解析与受控题库加载"
```

---

### Task 4: scripts/extract_question_bank.py — 官方 xlsx 提取（受控输出）

**Files:**
- Create: `scripts/extract_question_bank.py`
- Test: `tests/test_evaluation_extract.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_extract.py`（用 openpyxl 现场造合成 xlsx，绝不引用官方文件）：

```python
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from evaluation.question_bank import load_questions
from scripts.extract_question_bank import EXPECTED_HEADER, extract


def _make_workbook(path: Path, rows: list[list[str]], header: list[str] | None = None) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "问题答案清单"
    sheet.append(header or EXPECTED_HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


class ExtractQuestionBankTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "synthetic.xlsx"
        self.output = self.root / "data" / "private" / "evaluation" / "questions.jsonl"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_extracts_rows_to_jsonl(self) -> None:
        _make_workbook(
            self.source,
            [
                ["TRAIN-S-01", "单值", "简单", "合成题面一", "合成答案一"],
                ["VAL-M-01", "排名", "中等", "合成题面二", "合成答案二"],
                ["TST-H-01", "综合", "困难", "合成题面三", "合成答案三"],
            ],
        )
        count = extract(self.source, self.output, enforce_counts=False)
        self.assertEqual(count, 3)
        questions = load_questions(self.output)
        self.assertEqual(questions[0].question_id, "TRAIN-S-01")
        self.assertEqual(questions[0].partition, "TRAIN")
        self.assertEqual(questions[0].difficulty, "S")
        self.assertEqual(questions[1].question_type, "排名")
        self.assertEqual(questions[2].official_answer, "合成答案三")

    def test_rejects_unexpected_header(self) -> None:
        _make_workbook(
            self.source,
            [["TRAIN-S-01", "单值", "简单", "题", "答"]],
            header=["编号", "类型", "难度", "描述", "结果"],
        )
        with self.assertRaises(ValueError):
            extract(self.source, self.output, enforce_counts=False)

    def test_rejects_output_outside_private_dir(self) -> None:
        _make_workbook(self.source, [["TRAIN-S-01", "单值", "简单", "题", "答"]])
        unsafe_output = self.root / "public" / "questions.jsonl"
        with self.assertRaises(ValueError):
            extract(self.source, unsafe_output, enforce_counts=False)

    def test_enforce_counts_rejects_wrong_partition_sizes(self) -> None:
        _make_workbook(
            self.source,
            [["TRAIN-S-01", "单值", "简单", "题", "答"]],
        )
        with self.assertRaises(ValueError):
            extract(self.source, self.output, enforce_counts=True)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_extract -v
```

Expected: `ImportError`（scripts.extract_question_bank 不存在；`scripts/` 无 `__init__.py`，Python 3 namespace package 可直接按 `scripts.extract_question_bank` 导入，与现有仓库结构一致）

- [ ] **Step 3: 实现**

`scripts/extract_question_bank.py`：

```python
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.models import EvalQuestion
from evaluation.question_bank import parse_question_id, write_questions

EXPECTED_HEADER = ["问题编号", "问题类型", "问题难度", "问题描述", "问题结果"]
EXPECTED_COUNTS = {"TRAIN": 120, "VAL": 40, "TST": 40}
SHEET_NAME = "问题答案清单"


def extract(
    source: Path,
    output: Path,
    sheet_name: str = SHEET_NAME,
    enforce_counts: bool = True,
) -> int:
    from openpyxl import load_workbook

    output = Path(output).resolve()
    if "private" not in output.parts:
        raise ValueError(
            f"输出路径必须位于受控 private 目录内，拒绝写入：{output}。"
        )
    workbook = load_workbook(Path(source), read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name]
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]
        if header != EXPECTED_HEADER:
            raise ValueError(f"工作表表头不符合预期：{header}")
        questions: list[EvalQuestion] = []
        for raw in rows:
            if raw is None or raw[0] is None:
                continue
            question_id = str(raw[0]).strip()
            partition, difficulty = parse_question_id(question_id)
            questions.append(
                EvalQuestion(
                    question_id=question_id,
                    partition=partition,
                    difficulty=difficulty,
                    question_type=str(raw[1]).strip() if raw[1] is not None else "",
                    question_text=str(raw[3]).strip() if raw[3] is not None else "",
                    official_answer=str(raw[4]).strip() if raw[4] is not None else "",
                )
            )
    finally:
        workbook.close()

    counts = Counter(question.partition for question in questions)
    if enforce_counts and dict(counts) != EXPECTED_COUNTS:
        raise ValueError(f"分区题数与官方约定不符：{dict(counts)}，期望 {EXPECTED_COUNTS}。")

    write_questions(questions, output)
    return len(questions)


def main() -> int:
    parser = argparse.ArgumentParser(description="官方题库受控提取（输出进入 git 忽略目录）")
    parser.add_argument("--source", type=Path, required=True, help="官方 xlsx 路径（仓库外）")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "private" / "evaluation" / "questions.jsonl",
    )
    parser.add_argument("--allow-any-counts", action="store_true")
    args = parser.parse_args()
    count = extract(args.source, args.output, enforce_counts=not args.allow_any_counts)
    print(f"EXTRACTED={count} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_extract -v
```

Expected: `OK`（4 tests）

- [ ] **Step 5: 手动提取官方题库（本地受控，不提交）**

```powershell
.venv\Scripts\python.exe scripts\extract_question_bank.py --source "F:\1\Code\LearningProjects\FITC\基于大模型与NL2SQL的银行业智能问数系统构建与应用_数据集.xlsx"
git status --short
```

Expected: `EXTRACTED=200 -> ...data\private\evaluation\questions.jsonl`；`git status` **不出现** data/private（被忽略）。

- [ ] **Step 6: Commit**

```powershell
git add scripts/extract_question_bank.py tests/test_evaluation_extract.py
git commit -m "test: 官方题库受控提取脚本与守卫"
```

---

### Task 5: evaluation/normalization.py — 答案标准化

**Files:**
- Create: `evaluation/normalization.py`
- Test: `tests/test_evaluation_normalization.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_normalization.py`：

```python
import unittest

from evaluation.normalization import (
    RULES_VERSION,
    Number,
    extract_numbers,
    extract_org_names,
    normalize_date_expression,
    normalize_text,
)


class NormalizeTextTest(unittest.TestCase):
    def test_fullwidth_and_thousand_separators(self) -> None:
        self.assertEqual(normalize_text("１，２３４．５％"), "1234.5%")
        self.assertEqual(normalize_text("金额 1,234,567.89 元"), "金额 1234567.89 元")


class ExtractNumbersTest(unittest.TestCase):
    def test_amount_units_converted_to_yuan(self) -> None:
        numbers = extract_numbers("余额为1.5亿元，另有200万元和300元")
        self.assertEqual(
            numbers,
            [
                Number(value=150_000_000.0, kind="amount"),
                Number(value=2_000_000.0, kind="amount"),
                Number(value=300.0, kind="amount"),
            ],
        )

    def test_percent_vs_percent_point(self) -> None:
        numbers = extract_numbers("不良率为1.23%，比上月下降0.1个百分点")
        self.assertEqual(
            numbers,
            [
                Number(value=1.23, kind="percent"),
                Number(value=0.1, kind="percent_point"),
            ],
        )

    def test_plain_numbers_and_counts(self) -> None:
        numbers = extract_numbers("共有13家机构，排名第2")
        self.assertEqual(
            numbers,
            [Number(value=13.0, kind="plain"), Number(value=2.0, kind="plain")],
        )

    def test_no_numbers(self) -> None:
        self.assertEqual(extract_numbers("没有数值"), [])


class NormalizeDateTest(unittest.TestCase):
    def test_iso_kept(self) -> None:
        self.assertEqual(normalize_date_expression("2025-12-31"), "2025-12-31")

    def test_chinese_full_date(self) -> None:
        self.assertEqual(normalize_date_expression("2025年12月31日"), "2025-12-31")

    def test_month_end_expressions(self) -> None:
        self.assertEqual(normalize_date_expression("2025年12月末"), "2025-12-31")
        self.assertEqual(normalize_date_expression("2025年6月底"), "2025-06-30")
        self.assertEqual(normalize_date_expression("2024年2月末"), "2024-02-29")

    def test_unparseable_returns_none(self) -> None:
        self.assertIsNone(normalize_date_expression("最近一段时间"))


class ExtractOrgNamesTest(unittest.TestCase):
    def test_extracts_in_order_without_duplicates(self) -> None:
        text = "排名依次为测试省甲市农商行、测试省乙市农商行，其中测试省甲市农商行领先"
        self.assertEqual(
            extract_org_names(text),
            ["测试省甲市农商行", "测试省乙市农商行"],
        )

    def test_rules_version_present(self) -> None:
        self.assertTrue(RULES_VERSION.startswith("norm-"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_normalization -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`evaluation/normalization.py`：

```python
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

RULES_VERSION = "norm-2026.07.18-1"

_FULLWIDTH = str.maketrans(
    "０１２３４５６７８９．，％（）：",
    "0123456789.,%():",
)
_THOUSAND_SEP = re.compile(r"(?<=\d),(?=\d{3}\b)")
_AMOUNT = re.compile(r"(-?\d+(?:\.\d+)?)\s*(亿元|万元|元)")
_PERCENT_POINT = re.compile(r"(-?\d+(?:\.\d+)?)\s*个百分点")
_PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_PLAIN = re.compile(r"-?\d+(?:\.\d+)?")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DATE_CN_FULL = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
_DATE_CN_MONTH_END = re.compile(r"^(\d{4})年(\d{1,2})月(?:末|底)$")
_ORG_NAME = re.compile(r"[\u4e00-\u9fa5]{1,8}省[\u4e00-\u9fa5]{1,8}市农商行")

_AMOUNT_MULTIPLIER = {"亿元": 100_000_000.0, "万元": 10_000.0, "元": 1.0}


@dataclass(frozen=True)
class Number:
    value: float
    kind: str  # amount | percent | percent_point | plain


def normalize_text(text: str) -> str:
    normalized = text.translate(_FULLWIDTH).replace("，", ",")
    while _THOUSAND_SEP.search(normalized):
        normalized = _THOUSAND_SEP.sub("", normalized)
    return normalized


def extract_numbers(text: str) -> list[Number]:
    normalized = normalize_text(text)
    matches: list[tuple[int, Number]] = []
    consumed: list[tuple[int, int]] = []

    for pattern, kind in (
        (_AMOUNT, "amount"),
        (_PERCENT_POINT, "percent_point"),
        (_PERCENT, "percent"),
    ):
        for match in pattern.finditer(normalized):
            value = float(match.group(1))
            if kind == "amount":
                value *= _AMOUNT_MULTIPLIER[match.group(2)]
            matches.append((match.start(), Number(value=value, kind=kind)))
            consumed.append((match.start(), match.end()))

    for match in _PLAIN.finditer(normalized):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        matches.append(
            (match.start(), Number(value=float(match.group(0)), kind="plain"))
        )

    matches.sort(key=lambda item: item[0])
    return [number for _, number in matches]


def normalize_date_expression(text: str) -> str | None:
    stripped = normalize_text(text.strip())
    match = _DATE_ISO.match(stripped)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = _DATE_CN_FULL.match(stripped)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    match = _DATE_CN_MONTH_END.match(stripped)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def extract_org_names(text: str) -> list[str]:
    seen: list[str] = []
    for match in _ORG_NAME.finditer(text):
        name = match.group(0)
        if name not in seen:
            seen.append(name)
    return seen
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_normalization -v
```

Expected: `OK`（10 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/normalization.py tests/test_evaluation_normalization.py
git commit -m "test: 答案标准化规则（金额/百分比/日期/机构/版本化）"
```

---

### Task 6: evaluation/scoring.py — 自动判分（诚实兜底）

**Files:**
- Create: `evaluation/scoring.py`
- Test: `tests/test_evaluation_scoring.py`

判分策略（v1）：有系统错误 → `NOT_SCORED_SYSTEM_ERROR`；题号在异常清单 → `EXCLUDED_ANOMALY`；官方答案含 ≥2 机构名 → 机构序列必须按序出现在系统输出（若官方还有数值，数值也须全部匹配）；否则官方答案含数值 → 每个官方数值须在系统输出中找到同类数值容差匹配（金额统一到元，rel=1e-4 或 abs=0.01）；两类都提取不到 → `NEEDS_MANUAL_REVIEW`。

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_scoring.py`：

```python
import unittest

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_EXCLUDED_ANOMALY,
    SCORE_INCORRECT,
    SCORE_NEEDS_MANUAL_REVIEW,
    SCORE_NOT_SCORED_SYSTEM_ERROR,
    EvalQuestion,
)
from evaluation.scoring import RULES_VERSION, score


def _question(official_answer: str, question_id: str = "TRAIN-S-01") -> EvalQuestion:
    return EvalQuestion(
        question_id=question_id,
        partition="TRAIN",
        difficulty="S",
        question_type="合成",
        question_text="合成题面",
        official_answer=official_answer,
    )


class ScoreSystemStatesTest(unittest.TestCase):
    def test_system_error_is_not_scored(self) -> None:
        result = score(
            _question("答案为1.5亿元"),
            summary=None,
            rows=[],
            error_code="QUERY_TIMEOUT",
        )
        self.assertEqual(result.status, SCORE_NOT_SCORED_SYSTEM_ERROR)

    def test_anomaly_question_is_excluded(self) -> None:
        result = score(
            _question("答案为1.5亿元", question_id="TRAIN-M-46"),
            summary="任意",
            rows=[],
            anomaly_ids=frozenset({"TRAIN-M-46"}),
        )
        self.assertEqual(result.status, SCORE_EXCLUDED_ANOMALY)


class ScoreNumericTest(unittest.TestCase):
    def test_correct_when_all_official_numbers_match(self) -> None:
        result = score(
            _question("余额为1.5亿元"),
            summary="查询结果：余额合计15000.00万元",
            rows=[["合计", 150000000]],
        )
        self.assertEqual(result.status, SCORE_CORRECT)

    def test_incorrect_when_number_differs(self) -> None:
        result = score(
            _question("不良率为1.23%"),
            summary="不良率为1.32%",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_INCORRECT)

    def test_rows_participate_in_matching(self) -> None:
        result = score(
            _question("净利润为300元"),
            summary="查询返回1条记录。",
            rows=[["测试省甲市农商行", 300]],
        )
        self.assertEqual(result.status, SCORE_CORRECT)


class ScoreOrgListTest(unittest.TestCase):
    def test_correct_when_org_sequence_matches_in_order(self) -> None:
        result = score(
            _question("前两名依次为测试省甲市农商行、测试省乙市农商行"),
            summary="排名：1. 测试省甲市农商行 2. 测试省乙市农商行",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_CORRECT)

    def test_incorrect_when_order_swapped(self) -> None:
        result = score(
            _question("前两名依次为测试省甲市农商行、测试省乙市农商行"),
            summary="排名：1. 测试省乙市农商行 2. 测试省甲市农商行",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_INCORRECT)

    def test_incorrect_when_org_missing(self) -> None:
        result = score(
            _question("前两名依次为测试省甲市农商行、测试省乙市农商行"),
            summary="仅返回测试省甲市农商行",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_INCORRECT)


class ScoreHonestFallbackTest(unittest.TestCase):
    def test_unparseable_official_answer_needs_manual_review(self) -> None:
        result = score(
            _question("整体经营稳健，无明显异常"),
            summary="系统摘要",
            rows=[],
        )
        self.assertEqual(result.status, SCORE_NEEDS_MANUAL_REVIEW)

    def test_rules_version(self) -> None:
        self.assertTrue(RULES_VERSION.startswith("score-"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_scoring -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`evaluation/scoring.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_EXCLUDED_ANOMALY,
    SCORE_INCORRECT,
    SCORE_NEEDS_MANUAL_REVIEW,
    SCORE_NOT_SCORED_SYSTEM_ERROR,
    EvalQuestion,
)
from evaluation.normalization import Number, extract_numbers, extract_org_names

RULES_VERSION = "score-2026.07.18-1"

_REL_TOLERANCE = 1e-4
_ABS_TOLERANCE = 0.01


@dataclass(frozen=True)
class ScoreResult:
    status: str
    reason: str


def score(
    question: EvalQuestion,
    *,
    summary: str | None,
    rows: list[list[Any]],
    error_code: str | None = None,
    anomaly_ids: frozenset[str] = frozenset(),
) -> ScoreResult:
    if error_code:
        return ScoreResult(
            SCORE_NOT_SCORED_SYSTEM_ERROR, f"系统返回错误 {error_code}，不参与判分。"
        )
    if question.question_id in anomaly_ids:
        return ScoreResult(SCORE_EXCLUDED_ANOMALY, "题号命中已确认异常清单，单列统计。")

    system_text = _system_text(summary, rows)
    official_orgs = extract_org_names(question.official_answer)
    official_numbers = extract_numbers(question.official_answer)

    checked = False
    if len(official_orgs) >= 2:
        checked = True
        system_orgs = extract_org_names(system_text)
        if not _is_subsequence(official_orgs, system_orgs):
            if set(official_orgs) <= set(system_orgs):
                return ScoreResult(SCORE_INCORRECT, "机构集合一致但顺序不一致。")
            return ScoreResult(SCORE_INCORRECT, "官方答案要求的机构未全部出现。")

    if official_numbers:
        checked = True
        system_numbers = extract_numbers(system_text)
        missing = [
            official
            for official in official_numbers
            if not _has_match(official, system_numbers)
        ]
        if missing:
            return ScoreResult(
                SCORE_INCORRECT,
                f"官方答案中 {len(missing)} 个数值未在系统输出中匹配。",
            )

    if not checked:
        return ScoreResult(
            SCORE_NEEDS_MANUAL_REVIEW, "官方答案无法可靠解析为数值或机构序列，需人工判分。"
        )
    return ScoreResult(SCORE_CORRECT, "官方答案的机构与数值均在系统输出中匹配。")


def _system_text(summary: str | None, rows: list[list[Any]]) -> str:
    flattened = " ".join(
        str(cell) for row in rows for cell in row if cell is not None
    )
    return f"{summary or ''} {flattened}".strip()


def _is_subsequence(expected: list[str], actual: list[str]) -> bool:
    iterator = iter(actual)
    return all(name in iterator for name in expected)


def _has_match(official: Number, candidates: list[Number]) -> bool:
    compatible = {
        "amount": {"amount", "plain"},
        "percent": {"percent", "plain"},
        "percent_point": {"percent_point", "percent", "plain"},
        "plain": {"plain", "amount", "percent", "percent_point"},
    }[official.kind]
    for candidate in candidates:
        if candidate.kind not in compatible:
            continue
        tolerance = max(_ABS_TOLERANCE, abs(official.value) * _REL_TOLERANCE)
        if abs(candidate.value - official.value) <= tolerance:
            return True
    return False
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_scoring -v
```

Expected: `OK`（10 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/scoring.py tests/test_evaluation_scoring.py
git commit -m "test: 按题型自动判分与诚实人工复核兜底"
```

---

### Task 7: evaluation/attribution.py — 第一层归因

**Files:**
- Create: `evaluation/attribution.py`
- Test: `tests/test_evaluation_attribution.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_attribution.py`：

```python
import unittest

from evaluation.attribution import attribute
from evaluation.models import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    SCORE_NEEDS_MANUAL_REVIEW,
)


class AttributionTest(unittest.TestCase):
    def test_semantic_errors(self) -> None:
        for code in (
            "UNSUPPORTED_QUESTION",
            "CLARIFICATION_REQUIRED",
            "INVALID_SEMANTIC_OUTPUT",
            "UNSUPPORTED_METRIC",
            "INVALID_QUESTION",
        ):
            with self.subTest(code=code):
                result = attribute(code, SCORE_CORRECT)
                assert result is not None
                self.assertEqual(result.stage, "语义理解")

    def test_stage_mapping_samples(self) -> None:
        cases = {
            "INVALID_SQL_OUTPUT": "SQL生成",
            "LLM_TIMEOUT": "模型可用性",
            "LLM_UNAVAILABLE": "模型可用性",
            "LLM_PROVIDER_ERROR": "模型可用性",
            "SQL_REJECTED": "安全层",
            "ACCESS_DENIED": "安全层",
            "QUERY_EXECUTION_ERROR": "数据库执行",
            "QUERY_TIMEOUT": "数据库执行",
            "DATABASE_UNAVAILABLE": "数据库执行",
            "REQUEST_VALIDATION_ERROR": "接口校验",
            "API_CONNECTION_ERROR": "评测环境",
            "INTERNAL_ERROR": "系统内部",
        }
        for code, stage in cases.items():
            with self.subTest(code=code):
                result = attribute(code, SCORE_CORRECT)
                assert result is not None
                self.assertEqual(result.stage, stage)

    def test_unknown_code_falls_back(self) -> None:
        result = attribute("SOMETHING_NEW", SCORE_CORRECT)
        assert result is not None
        self.assertEqual(result.stage, "未分类错误")

    def test_no_error_correct_returns_none(self) -> None:
        self.assertIsNone(attribute(None, SCORE_CORRECT))

    def test_no_error_incorrect_is_result_mismatch(self) -> None:
        result = attribute(None, SCORE_INCORRECT)
        assert result is not None
        self.assertEqual(result.stage, "结果不一致")
        self.assertIn("06号", result.owner)

    def test_no_error_manual_review(self) -> None:
        result = attribute(None, SCORE_NEEDS_MANUAL_REVIEW)
        assert result is not None
        self.assertEqual(result.stage, "待人工判分")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_attribution -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`evaluation/attribution.py`：

```python
from __future__ import annotations

from dataclasses import dataclass

from evaluation.models import SCORE_CORRECT, SCORE_NEEDS_MANUAL_REVIEW


@dataclass(frozen=True)
class Attribution:
    stage: str
    owner: str


_SEMANTIC = Attribution("语义理解", "05号复核业务口径；技术实现交项目负责人")
_SQL_GENERATION = Attribution("SQL生成", "生成模块开发成员/项目负责人")
_MODEL = Attribution("模型可用性", "项目负责人")
_SAFETY = Attribution("安全层", "安全模块开发成员/项目负责人")
_DATABASE = Attribution("数据库执行", "04号数据负责人")
_VALIDATION = Attribution("接口校验", "06号检查评测输入")
_ENVIRONMENT = Attribution("评测环境", "06号检查后端服务与网络")
_INTERNAL = Attribution("系统内部", "项目负责人")
_UNKNOWN = Attribution("未分类错误", "06号人工归因")

_ERROR_STAGE_MAP: dict[str, Attribution] = {
    "UNSUPPORTED_QUESTION": _SEMANTIC,
    "CLARIFICATION_REQUIRED": _SEMANTIC,
    "INVALID_SEMANTIC_OUTPUT": _SEMANTIC,
    "UNSUPPORTED_METRIC": _SEMANTIC,
    "INVALID_QUESTION": _SEMANTIC,
    "INVALID_SQL_OUTPUT": _SQL_GENERATION,
    "LLM_TIMEOUT": _MODEL,
    "LLM_UNAVAILABLE": _MODEL,
    "LLM_PROVIDER_ERROR": _MODEL,
    "SQL_REJECTED": _SAFETY,
    "ACCESS_DENIED": _SAFETY,
    "QUERY_EXECUTION_ERROR": _DATABASE,
    "QUERY_TIMEOUT": _DATABASE,
    "DATABASE_UNAVAILABLE": _DATABASE,
    "REQUEST_VALIDATION_ERROR": _VALIDATION,
    "API_CONNECTION_ERROR": _ENVIRONMENT,
    "INTERNAL_ERROR": _INTERNAL,
}


def attribute(error_code: str | None, score_status: str) -> Attribution | None:
    if error_code:
        return _ERROR_STAGE_MAP.get(error_code, _UNKNOWN)
    if score_status == SCORE_CORRECT:
        return None
    if score_status == SCORE_NEEDS_MANUAL_REVIEW:
        return Attribution("待人工判分", "06号人工判分后再归因")
    return Attribution("结果不一致", "06号人工复核证据后分派05号/04号/开发成员")
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_attribution -v
```

Expected: `OK`（6 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/attribution.py tests/test_evaluation_attribution.py
git commit -m "test: 错误码到失败阶段的第一层归因映射"
```

---

### Task 8: evaluation/reporting.py — 汇总与脱敏摘要

**Files:**
- Create: `evaluation/reporting.py`
- Test: `tests/test_evaluation_reporting.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_reporting.py`：

```python
import unittest

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    SCORE_NOT_SCORED_SYSTEM_ERROR,
    EvalRecord,
)
from evaluation.reporting import summarize, to_public_markdown


def _record(
    question_id: str,
    partition: str,
    difficulty: str,
    score_status: str,
    route: str | None = "RULE",
    error_code: str | None = None,
    sql: str | None = "SELECT 1",
    elapsed_ms: int | None = 100,
    stage: str | None = None,
) -> EvalRecord:
    return EvalRecord(
        question_id=question_id,
        partition=partition,
        difficulty=difficulty,
        question_type="合成",
        run_id="run-1",
        started_at="2026-07-18T10:00:00",
        elapsed_ms=elapsed_ms,
        route=route,
        sql=sql,
        error_code=error_code,
        score_status=score_status,
        attribution_stage=stage,
    )


class SummarizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _record("TRAIN-S-01", "TRAIN", "S", SCORE_CORRECT, elapsed_ms=100),
            _record("TRAIN-S-02", "TRAIN", "S", SCORE_INCORRECT, elapsed_ms=200, stage="结果不一致"),
            _record(
                "TRAIN-M-01",
                "TRAIN",
                "M",
                SCORE_NOT_SCORED_SYSTEM_ERROR,
                route="LLM",
                error_code="QUERY_TIMEOUT",
                sql=None,
                elapsed_ms=400,
                stage="数据库执行",
            ),
            _record("VAL-S-01", "VAL", "S", SCORE_CORRECT, elapsed_ms=300),
        ]

    def test_totals_and_rates(self) -> None:
        summary = summarize(self.records)
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["by_partition"]["TRAIN"]["total"], 3)
        self.assertEqual(summary["score_counts"][SCORE_CORRECT], 2)
        self.assertAlmostEqual(summary["rates"]["sql_generated"], 3 / 4)
        self.assertAlmostEqual(summary["rates"]["no_error"], 3 / 4)
        self.assertAlmostEqual(summary["rates"]["end_to_end_correct"], 2 / 4)
        self.assertAlmostEqual(summary["rates"]["correct_among_scored"], 2 / 3)

    def test_latency_percentiles(self) -> None:
        summary = summarize(self.records)
        self.assertEqual(summary["latency_ms"]["p50"], 200)
        self.assertEqual(summary["latency_ms"]["p95"], 400)

    def test_failure_stages_counted(self) -> None:
        summary = summarize(self.records)
        self.assertEqual(summary["failure_stages"]["数据库执行"], 1)
        self.assertEqual(summary["failure_stages"]["结果不一致"], 1)

    def test_empty_records(self) -> None:
        summary = summarize([])
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["latency_ms"]["p50"])


class PublicMarkdownTest(unittest.TestCase):
    def test_contains_aggregates_only(self) -> None:
        summary = summarize(
            [_record("TRAIN-S-01", "TRAIN", "S", SCORE_CORRECT)]
        )
        markdown = to_public_markdown(summary, run_id="run-1")
        self.assertIn("run-1", markdown)
        self.assertIn("总题数", markdown)
        self.assertNotIn("TRAIN-S-01", markdown)
        self.assertNotIn("SELECT", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_reporting -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`evaluation/reporting.py`：

```python
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_EXCLUDED_ANOMALY,
    SCORE_NEEDS_MANUAL_REVIEW,
    EvalRecord,
)


def summarize(records: list[EvalRecord]) -> dict[str, Any]:
    total = len(records)
    score_counts: Counter[str] = Counter(record.score_status for record in records)
    by_partition: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "correct": 0}
    )
    by_difficulty: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "correct": 0}
    )
    by_route: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "correct": 0}
    )
    failure_stages: Counter[str] = Counter()
    latencies: list[int] = []

    for record in records:
        for bucket, key in (
            (by_partition, record.partition),
            (by_difficulty, record.difficulty),
            (by_route, record.route or "UNKNOWN"),
        ):
            bucket[key]["total"] += 1
            if record.score_status == SCORE_CORRECT:
                bucket[key]["correct"] += 1
        if record.attribution_stage:
            failure_stages[record.attribution_stage] += 1
        if record.elapsed_ms is not None:
            latencies.append(record.elapsed_ms)

    scored = sum(
        count
        for status, count in score_counts.items()
        if status not in {SCORE_NEEDS_MANUAL_REVIEW, SCORE_EXCLUDED_ANOMALY}
    )
    correct = score_counts.get(SCORE_CORRECT, 0)
    sql_generated = sum(1 for record in records if record.sql)
    no_error = sum(1 for record in records if record.error_code is None)

    return {
        "total": total,
        "score_counts": dict(score_counts),
        "by_partition": {key: dict(value) for key, value in by_partition.items()},
        "by_difficulty": {key: dict(value) for key, value in by_difficulty.items()},
        "by_route": {key: dict(value) for key, value in by_route.items()},
        "failure_stages": dict(failure_stages),
        "rates": {
            "sql_generated": _rate(sql_generated, total),
            "no_error": _rate(no_error, total),
            "end_to_end_correct": _rate(correct, total),
            "correct_among_scored": _rate(correct, scored),
        },
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
    }


def to_public_markdown(summary: dict[str, Any], run_id: str) -> str:
    lines = [
        f"# 评测汇总（脱敏公开版）：{run_id}",
        "",
        f"- 总题数：{summary['total']}",
        f"- 端到端正确率：{_fmt_rate(summary['rates']['end_to_end_correct'])}",
        f"- 已判分正确率：{_fmt_rate(summary['rates']['correct_among_scored'])}",
        f"- SQL 生成率：{_fmt_rate(summary['rates']['sql_generated'])}",
        f"- 无错误率：{_fmt_rate(summary['rates']['no_error'])}",
        f"- 耗时 P50/P95/Max(ms)：{summary['latency_ms']['p50']}"
        f"/{summary['latency_ms']['p95']}/{summary['latency_ms']['max']}",
        "",
        "## 按分区",
    ]
    for key, value in sorted(summary["by_partition"].items()):
        lines.append(f"- {key}: {value['correct']}/{value['total']}")
    lines.append("")
    lines.append("## 失败阶段分布（脱敏）")
    for stage, count in sorted(summary["failure_stages"].items()):
        lines.append(f"- {stage}: {count}")
    lines.append("")
    return "\n".join(lines)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _fmt_rate(rate: float | None) -> str:
    return "N/A" if rate is None else f"{rate * 100:.1f}%"


def _percentile(values: list[int], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(ratio * len(ordered)) - 1))
    return ordered[index]
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_reporting -v
```

Expected: `OK`（5 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/reporting.py tests/test_evaluation_reporting.py
git commit -m "test: 评测汇总指标与脱敏公开摘要"
```

---

### Task 9: evaluation/runner.py — 批量执行、断点续跑、连续失败中止

**Files:**
- Create: `evaluation/runner.py`
- Test: `tests/test_evaluation_runner.py`

Runner 不 import `frontend.*`；client 为鸭子类型：`client.query(question, user_id=..., conversation_id=...)` 返回带 `.payload`（dict）与 `.elapsed_ms`（int）属性的对象。client 抛出的任何异常记为 `API_CONNECTION_ERROR`，连续 3 次中止。

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_runner.py`：

```python
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from evaluation.models import EvalQuestion, EvalRecord
from evaluation.runner import EvaluationRunner, RunContext


@dataclass
class FakeResult:
    payload: dict
    elapsed_ms: int = 50


class FakeClient:
    def __init__(self, payloads: dict[str, dict | Exception]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def query(self, question: str, user_id: str = "", conversation_id: str = "") -> FakeResult:
        self.calls.append(question)
        outcome = self.payloads[question]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResult(payload=outcome)


def _question(question_id: str, text: str) -> EvalQuestion:
    partition, difficulty, _ = question_id.split("-")
    return EvalQuestion(
        question_id=question_id,
        partition=partition,
        difficulty=difficulty,
        question_type="合成",
        question_text=text,
        official_answer="净利润为300元",
    )


def _ok_payload(sql: str = "SELECT 1") -> dict:
    return {
        "request_id": "req_x",
        "question": "q",
        "sql": sql,
        "columns": ["metric"],
        "rows": [["净利润", 300]],
        "summary": "净利润为300元",
        "warnings": [],
        "error": None,
        "metadata": {
            "configured_mode": "hybrid",
            "executed_generator": "rule",
            "rule_matched": True,
            "route": "RULE",
            "failure_reason": None,
            "provider": None,
            "model": None,
            "llm_latency_ms": None,
            "semantic": None,
            "fallback": {"used": False, "reason": None, "fallback_generator": None},
        },
    }


def _error_payload(code: str) -> dict:
    payload = _ok_payload(sql=None)
    payload["rows"] = []
    payload["summary"] = None
    payload["error"] = {"code": code, "message": "结构化错误", "retryable": False}
    return payload


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.context = RunContext(
            run_id="run-t",
            data_dir=self.data_dir,
            code_version="abc1234",
            model="deepseek-v4-flash",
            db_label="demo",
            configured_mode_label="hybrid",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _details_path(self) -> Path:
        return self.data_dir / "runs" / "run-t" / "details.jsonl"

    def test_writes_details_summary_and_scores(self) -> None:
        questions = [_question("TRAIN-S-01", "问一"), _question("TRAIN-S-02", "问二")]
        client = FakeClient({"问一": _ok_payload(), "问二": _error_payload("QUERY_TIMEOUT")})
        runner = EvaluationRunner(client, self.context)

        summary = runner.run(questions)

        lines = self._details_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        first = EvalRecord.from_json_line(lines[0])
        self.assertEqual(first.question_id, "TRAIN-S-01")
        self.assertEqual(first.score_status, "CORRECT")
        self.assertEqual(first.code_version, "abc1234")
        second = EvalRecord.from_json_line(lines[1])
        self.assertEqual(second.error_code, "QUERY_TIMEOUT")
        self.assertEqual(second.attribution_stage, "数据库执行")
        self.assertEqual(summary["total"], 2)
        summary_path = self.data_dir / "runs" / "run-t" / "summary.json"
        self.assertTrue(summary_path.is_file())
        self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["total"], 2)

    def test_resume_skips_completed_questions(self) -> None:
        questions = [_question("TRAIN-S-01", "问一"), _question("TRAIN-S-02", "问二")]
        client_first = FakeClient({"问一": _ok_payload(), "问二": _ok_payload()})
        EvaluationRunner(client_first, self.context).run([questions[0]])

        client_second = FakeClient({"问一": _ok_payload(), "问二": _ok_payload()})
        EvaluationRunner(client_second, self.context).run(questions)

        self.assertEqual(client_second.calls, ["问二"])
        lines = self._details_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_aborts_after_consecutive_connection_failures(self) -> None:
        questions = [
            _question("TRAIN-S-01", "问一"),
            _question("TRAIN-S-02", "问二"),
            _question("TRAIN-S-03", "问三"),
            _question("TRAIN-S-04", "问四"),
        ]
        client = FakeClient(
            {
                "问一": RuntimeError("连接失败"),
                "问二": RuntimeError("连接失败"),
                "问三": RuntimeError("连接失败"),
                "问四": _ok_payload(),
            }
        )
        runner = EvaluationRunner(client, self.context)
        with self.assertRaises(RuntimeError):
            runner.run(questions)
        lines = self._details_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        record = EvalRecord.from_json_line(lines[0])
        self.assertEqual(record.error_code, "API_CONNECTION_ERROR")
        self.assertEqual(record.attribution_stage, "评测环境")

    def test_rows_truncated_to_stored_limit(self) -> None:
        payload = _ok_payload()
        payload["rows"] = [["行", index] for index in range(80)]
        client = FakeClient({"问一": payload})
        runner = EvaluationRunner(client, self.context, max_stored_rows=50)
        runner.run([_question("TRAIN-S-01", "问一")])
        record = EvalRecord.from_json_line(
            self._details_path().read_text(encoding="utf-8").strip()
        )
        self.assertEqual(len(record.rows), 50)
        self.assertEqual(record.total_row_count, 80)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_runner -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`evaluation/runner.py`：

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from evaluation.attribution import attribute
from evaluation.models import EvalQuestion, EvalRecord
from evaluation.normalization import RULES_VERSION as NORM_RULES_VERSION
from evaluation.reporting import summarize
from evaluation.scoring import RULES_VERSION as SCORE_RULES_VERSION, score


class QueryClient(Protocol):
    def query(self, question: str, user_id: str = ..., conversation_id: str = ...) -> Any: ...


@dataclass(frozen=True)
class RunContext:
    run_id: str
    data_dir: Path
    code_version: str | None = None
    model: str | None = None
    db_label: str | None = None
    configured_mode_label: str | None = None


class EvaluationRunner:
    def __init__(
        self,
        client: QueryClient,
        context: RunContext,
        *,
        max_consecutive_connection_failures: int = 3,
        max_stored_rows: int = 50,
    ) -> None:
        self.client = client
        self.context = context
        self.max_consecutive_connection_failures = max_consecutive_connection_failures
        self.max_stored_rows = max_stored_rows

    def run(
        self,
        questions: list[EvalQuestion],
        anomaly_ids: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        run_dir = Path(self.context.data_dir) / "runs" / self.context.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        details_path = run_dir / "details.jsonl"
        completed = self._load_completed_ids(details_path)

        consecutive_failures = 0
        with details_path.open("a", encoding="utf-8", newline="\n") as handle:
            for question in questions:
                if question.question_id in completed:
                    continue
                record = self._execute_one(question, anomaly_ids)
                handle.write(record.to_json_line() + "\n")
                handle.flush()
                if record.error_code == "API_CONNECTION_ERROR":
                    consecutive_failures += 1
                    if consecutive_failures >= self.max_consecutive_connection_failures:
                        raise RuntimeError(
                            f"连续 {consecutive_failures} 次无法连接后端，评测中止；"
                            f"已完成记录保留在 {details_path}，可修复后续跑。"
                        )
                else:
                    consecutive_failures = 0

        records = self._load_records(details_path)
        summary = summarize(records)
        summary["run_id"] = self.context.run_id
        summary["code_version"] = self.context.code_version
        summary["model"] = self.context.model
        summary["db_label"] = self.context.db_label
        summary["configured_mode_label"] = self.context.configured_mode_label
        summary["rules_version"] = self._rules_version()
        summary_path = run_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary

    def _execute_one(
        self, question: EvalQuestion, anomaly_ids: frozenset[str]
    ) -> EvalRecord:
        record = EvalRecord(
            question_id=question.question_id,
            partition=question.partition,
            difficulty=question.difficulty,
            question_type=question.question_type,
            run_id=self.context.run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            code_version=self.context.code_version,
            model=self.context.model,
            db_label=self.context.db_label,
            rules_version=self._rules_version(),
        )
        try:
            result = self.client.query(
                question.question_text,
                user_id="evaluation",
                conversation_id=self.context.run_id,
            )
        except Exception as exc:
            record.error_code = "API_CONNECTION_ERROR"
            record.error_message = f"{type(exc).__name__}"
            record.score_status = "NOT_SCORED_SYSTEM_ERROR"
            record.score_reason = "后端连接失败，未获得响应。"
        else:
            payload = result.payload
            record.elapsed_ms = result.elapsed_ms
            record.sql = payload.get("sql")
            record.columns = payload.get("columns") or []
            rows = payload.get("rows") or []
            record.total_row_count = len(rows)
            record.rows = rows[: self.max_stored_rows]
            record.summary = payload.get("summary")
            error = payload.get("error")
            if error:
                record.error_code = error.get("code")
                record.error_message = error.get("message")
            metadata = payload.get("metadata") or {}
            record.configured_mode = metadata.get("configured_mode")
            record.executed_generator = metadata.get("executed_generator")
            record.rule_matched = metadata.get("rule_matched")
            record.route = metadata.get("route")
            record.semantic = metadata.get("semantic")
            record.llm_latency_ms = metadata.get("llm_latency_ms")
            score_result = score(
                question,
                summary=record.summary,
                rows=rows,
                error_code=record.error_code,
                anomaly_ids=anomaly_ids,
            )
            record.score_status = score_result.status
            record.score_reason = score_result.reason

        attribution = attribute(record.error_code, record.score_status)
        if attribution:
            record.attribution_stage = attribution.stage
            record.attribution_owner = attribution.owner
        return record

    @staticmethod
    def _rules_version() -> str:
        return f"{NORM_RULES_VERSION}+{SCORE_RULES_VERSION}"

    @staticmethod
    def _load_completed_ids(details_path: Path) -> set[str]:
        if not details_path.is_file():
            return set()
        completed: set[str] = set()
        with details_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    completed.add(json.loads(line)["question_id"])
        return completed

    @staticmethod
    def _load_records(details_path: Path) -> list[EvalRecord]:
        records: list[EvalRecord] = []
        with details_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(EvalRecord.from_json_line(line))
        return records
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_runner -v
```

Expected: `OK`（4 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/runner.py tests/test_evaluation_runner.py
git commit -m "test: 批量评测Runner（断点续跑与连续失败中止）"
```

---

### Task 10: evaluation/compare.py — 版本回归对比

**Files:**
- Create: `evaluation/compare.py`
- Test: `tests/test_evaluation_compare.py`

- [ ] **Step 1: 写失败测试**

`tests/test_evaluation_compare.py`：

```python
import tempfile
import unittest
from pathlib import Path

from evaluation.compare import compare_runs, load_run_records, to_markdown
from evaluation.models import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    EvalRecord,
)


def _record(
    question_id: str,
    score_status: str,
    error_code: str | None = None,
    elapsed_ms: int = 100,
    run_id: str = "run",
) -> EvalRecord:
    return EvalRecord(
        question_id=question_id,
        partition="TRAIN",
        difficulty="S",
        question_type="合成",
        run_id=run_id,
        started_at="t",
        elapsed_ms=elapsed_ms,
        error_code=error_code,
        score_status=score_status,
    )


def _write_run(root: Path, run_id: str, records: list[EvalRecord]) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    with (run_dir / "details.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.to_json_line() + "\n")


class CompareRunsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        _write_run(
            self.root,
            "old",
            [
                _record("TRAIN-S-01", SCORE_INCORRECT, run_id="old"),
                _record("TRAIN-S-02", SCORE_CORRECT, run_id="old", elapsed_ms=100),
                _record("TRAIN-S-03", SCORE_CORRECT, run_id="old"),
            ],
        )
        _write_run(
            self.root,
            "new",
            [
                _record("TRAIN-S-01", SCORE_CORRECT, run_id="new"),
                _record("TRAIN-S-02", SCORE_INCORRECT, run_id="new", elapsed_ms=300),
                _record(
                    "TRAIN-S-03",
                    "NOT_SCORED_SYSTEM_ERROR",
                    error_code="QUERY_TIMEOUT",
                    run_id="new",
                ),
            ],
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_improved_regressed_and_new_errors(self) -> None:
        old = load_run_records(self.root, "old")
        new = load_run_records(self.root, "new")
        result = compare_runs(old, new)
        self.assertEqual(result["improved"], ["TRAIN-S-01"])
        self.assertEqual(sorted(result["regressed"]), ["TRAIN-S-02", "TRAIN-S-03"])
        self.assertEqual(result["new_errors"], ["TRAIN-S-03"])
        self.assertAlmostEqual(result["correct_rate_delta"], (1 / 3) - (2 / 3))

    def test_markdown_contains_ids_but_no_question_text(self) -> None:
        old = load_run_records(self.root, "old")
        new = load_run_records(self.root, "new")
        markdown = to_markdown(compare_runs(old, new), old_run_id="old", new_run_id="new")
        self.assertIn("TRAIN-S-01", markdown)
        self.assertIn("退化", markdown)

    def test_missing_run_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_run_records(self.root, "absent")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_compare -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`evaluation/compare.py`：

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from evaluation.models import SCORE_CORRECT, EvalRecord


def load_run_records(data_dir: Path, run_id: str) -> dict[str, EvalRecord]:
    details_path = Path(data_dir) / "runs" / run_id / "details.jsonl"
    if not details_path.is_file():
        raise FileNotFoundError(f"找不到评测记录：{details_path}")
    records: dict[str, EvalRecord] = {}
    with details_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                record = EvalRecord.from_json_line(line)
                records[record.question_id] = record
    return records


def compare_runs(
    old: dict[str, EvalRecord], new: dict[str, EvalRecord]
) -> dict[str, Any]:
    shared = sorted(set(old) & set(new))
    improved: list[str] = []
    regressed: list[str] = []
    new_errors: list[str] = []
    fixed_errors: list[str] = []
    latency_deltas: list[int] = []

    for question_id in shared:
        before, after = old[question_id], new[question_id]
        was_correct = before.score_status == SCORE_CORRECT
        is_correct = after.score_status == SCORE_CORRECT
        if not was_correct and is_correct:
            improved.append(question_id)
        elif was_correct and not is_correct:
            regressed.append(question_id)
        if before.error_code is None and after.error_code is not None:
            new_errors.append(question_id)
        elif before.error_code is not None and after.error_code is None:
            fixed_errors.append(question_id)
        if before.elapsed_ms is not None and after.elapsed_ms is not None:
            latency_deltas.append(after.elapsed_ms - before.elapsed_ms)

    return {
        "shared_total": len(shared),
        "only_in_old": sorted(set(old) - set(new)),
        "only_in_new": sorted(set(new) - set(old)),
        "improved": improved,
        "regressed": regressed,
        "new_errors": new_errors,
        "fixed_errors": fixed_errors,
        "correct_rate_delta": _correct_rate(new) - _correct_rate(old),
        "mean_latency_delta_ms": (
            sum(latency_deltas) / len(latency_deltas) if latency_deltas else None
        ),
    }


def to_markdown(result: dict[str, Any], old_run_id: str, new_run_id: str) -> str:
    lines = [
        f"# 版本回归对比（受控）：{old_run_id} -> {new_run_id}",
        "",
        f"- 共同题数：{result['shared_total']}",
        f"- 正确率变化：{result['correct_rate_delta'] * 100:+.1f} 个百分点",
        f"- 平均耗时变化：{result['mean_latency_delta_ms']} ms",
        "",
        f"## 改善题（{len(result['improved'])}）",
        *[f"- {question_id}" for question_id in result["improved"]],
        "",
        f"## 退化题（{len(result['regressed'])}）",
        *[f"- {question_id}" for question_id in result["regressed"]],
        "",
        f"## 新增错误（{len(result['new_errors'])}）",
        *[f"- {question_id}" for question_id in result["new_errors"]],
        "",
    ]
    return "\n".join(lines)


def _correct_rate(records: dict[str, EvalRecord]) -> float:
    if not records:
        return 0.0
    correct = sum(
        1 for record in records.values() if record.score_status == SCORE_CORRECT
    )
    return correct / len(records)
```

- [ ] **Step 4: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_compare -v
```

Expected: `OK`（3 tests）

- [ ] **Step 5: Commit**

```powershell
git add evaluation/compare.py tests/test_evaluation_compare.py
git commit -m "test: 版本回归对比（改善/退化/新增错误/耗时）"
```

---

### Task 11: scripts/run_evaluation.py — CLI 入口与首次基线

**Files:**
- Create: `scripts/run_evaluation.py`

CLI 不写自动化测试（纯组装层，逻辑已被上游单测覆盖），按 `stability_check.py` 先例。

- [ ] **Step 1: 实现**

`scripts/run_evaluation.py`：

```python
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.compare import compare_runs, load_run_records, to_markdown
from evaluation.question_bank import load_questions
from evaluation.runner import EvaluationRunner, RunContext
from frontend.api_client import BankInsightClient

PARTITION_CHOICES = {"train": "TRAIN", "val": "VAL", "test": "TST"}
DEFAULT_DATA_DIR = ROOT / "data" / "private" / "evaluation"


def _git_commit() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            or None
        )
    except Exception:
        return None


def _load_anomaly_ids(path: Path | None) -> frozenset[str]:
    if path is None:
        return frozenset()
    return frozenset(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def _cmd_run(args: argparse.Namespace) -> int:
    partitions = (
        None if args.partition == "all" else {PARTITION_CHOICES[args.partition]}
    )
    ids = set(args.ids.split(",")) if args.ids else None
    questions = load_questions(
        args.questions, partitions=partitions, ids=ids, limit=args.limit
    )
    if not questions:
        print("没有匹配的题目，请检查 --partition/--ids/--limit。")
        return 1
    client = BankInsightClient(args.base_url, timeout_seconds=args.timeout)
    context = RunContext(
        run_id=args.run_id,
        data_dir=args.data_dir,
        code_version=_git_commit(),
        model=args.model_label,
        db_label=args.db_label,
        configured_mode_label=args.mode_label,
    )
    runner = EvaluationRunner(client, context)
    summary = runner.run(questions, anomaly_ids=_load_anomaly_ids(args.anomaly_file))
    print(f"RUN={args.run_id} total={summary['total']}")
    print(f"rates={summary['rates']}")
    print(f"details={Path(args.data_dir) / 'runs' / args.run_id / 'details.jsonl'}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    old = load_run_records(args.data_dir, args.old)
    new = load_run_records(args.data_dir, args.new)
    result = compare_runs(old, new)
    markdown = to_markdown(result, old_run_id=args.old, new_run_id=args.new)
    output = Path(args.data_dir) / "runs" / args.new / f"compare_vs_{args.old}.md"
    output.write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"COMPARE_REPORT={output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="言出数行官方题库批量评测")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="批量评测")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    run_parser.add_argument(
        "--partition", choices=[*PARTITION_CHOICES, "all"], default="train"
    )
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument("--ids", default=None, help="逗号分隔题号，冒烟用")
    run_parser.add_argument(
        "--questions", type=Path, default=DEFAULT_DATA_DIR / "questions.jsonl"
    )
    run_parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    run_parser.add_argument("--anomaly-file", type=Path, default=None)
    run_parser.add_argument("--timeout", type=float, default=70.0)
    run_parser.add_argument("--mode-label", default=None)
    run_parser.add_argument("--model-label", default=None)
    run_parser.add_argument("--db-label", default="demo")
    run_parser.set_defaults(func=_cmd_run)

    compare_parser = subparsers.add_parser("compare", help="两个run对比")
    compare_parser.add_argument("--old", required=True)
    compare_parser.add_argument("--new", required=True)
    compare_parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    compare_parser.set_defaults(func=_cmd_compare)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 语法与帮助检查**

```powershell
.venv\Scripts\python.exe -m compileall -q scripts evaluation
.venv\Scripts\python.exe scripts\run_evaluation.py run --help
```

Expected: 无编译错误；打印 run 子命令帮助。

- [ ] **Step 3: 手动冒烟（5 题，hybrid，需真实 key；结果只落受控目录）**

前置：Task 4 Step 5 已提取 `questions.jsonl`；`.env` 已配置。

```powershell
# 终端 A：起后端
$env:PYTHONPATH = "backend"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 终端 B：冒烟 5 题
$env:PYTHONPATH = "backend;."
.venv\Scripts\python.exe scripts\run_evaluation.py run --run-id smoke-hybrid-01 --partition train --limit 5 --mode-label hybrid
git status --short
```

Expected: `RUN=smoke-hybrid-01 total=5`，rates 打印（Demo 库上预期大量非 CORRECT——这是预期基线行为）；`git status` 不出现 data/private。

- [ ] **Step 4: 手动全量基线（120 题训练分区，约 11-15 分钟）**

```powershell
.venv\Scripts\python.exe scripts\run_evaluation.py run --run-id baseline-demo-hybrid-01 --partition train --mode-label hybrid
```

Expected: 正常完成或断点续跑后完成；`runs/baseline-demo-hybrid-01/summary.json` 生成。此 run 即"首次基线"（交付物 4 的基线记录）。

- [ ] **Step 5: Commit**

```powershell
git add scripts/run_evaluation.py
git commit -m "test: 批量评测CLI（run/compare子命令与冒烟参数）"
```

---

### Task 12: tests/test_evaluation_special_cases.py — 固定专项用例库

**Files:**
- Test: `tests/test_evaluation_special_cases.py`

复用 `tests/test_api.py` 的 TestClient + temp db 模式（离线、不依赖官方数据、可进公开仓库）。

- [ ] **Step 1: 写测试（本任务测试即交付物，先跑通即可）**

`tests/test_evaluation_special_cases.py`：

```python
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.audit.noop_logger import NoOpAuditLogger
from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.database.init_db import initialize_database
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.formatting.template_formatter import TemplateResultFormatter
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.errors import QueryTimeoutError
from app.application.models import GeneratedSQL, QueryContext
from app.application.pipeline import QueryPipeline
from app.bootstrap.container import build_pipeline
from app.core.settings import Settings
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


class DangerousGenerator:
    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        return GeneratedSQL("DROP TABLE customer_info", generator_name="special-case")


class TimeoutExecutor:
    def execute_query(self, sql: str, parameters: dict, max_rows: int = 1000):
        raise QueryTimeoutError("数据库查询超时。")


class SpecialCaseSuite(unittest.TestCase):
    """Issue #6 交付物3：固定专项测试用例库（独立于官方题库，可公开运行）。"""

    def setUp(self) -> None:
        from app.api.query import get_query_pipeline

        self.get_query_pipeline = get_query_pipeline
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "bankinsight.db"
        initialize_database(self.database_path, ROOT / "sql" / "schema.sql")
        self.pipeline = build_pipeline(
            self.database_path, settings=Settings(generator_mode="rule")
        )
        app.dependency_overrides[self.get_query_pipeline] = lambda: self.pipeline
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self.tempdir.cleanup()

    def _post(self, question: str):
        return self.client.post(
            "/api/v1/query", json={"question": question, "user_id": "special_case"}
        )

    def _override_pipeline(self, **kwargs) -> None:
        defaults = dict(
            context_resolver=YAMLContextResolver(
                ROOT / "config" / "schema.yml", ROOT / "config" / "metrics.yml"
            ),
            sql_generator=RuleSQLGenerator(),
            safety_checker=SQLGlotSafetyChecker(),
            database_executor=SQLiteExecutor(self.database_path),
            result_formatter=TemplateResultFormatter(),
            audit_logger=NoOpAuditLogger(),
        )
        defaults.update(kwargs)
        app.dependency_overrides[self.get_query_pipeline] = lambda: QueryPipeline(
            **defaults
        )

    def test_empty_and_blank_question_returns_structured_422(self) -> None:
        for question in ("", "   "):
            with self.subTest(question=repr(question)):
                response = self._post(question)
                self.assertEqual(response.status_code, 422)
                body = response.json()
                self.assertEqual(body["error"]["code"], "REQUEST_VALIDATION_ERROR")
                self.assertEqual(body["rows"], [])

    def test_overlong_question_returns_structured_422(self) -> None:
        response = self._post("查" * 501)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"], "REQUEST_VALIDATION_ERROR"
        )

    def test_unknown_customer_returns_empty_result_not_error(self) -> None:
        response = self._post("查询客户C999的账户余额")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["error"])
        self.assertEqual(body["rows"], [])

    def test_out_of_range_period_returns_empty_result_not_error(self) -> None:
        response = self._post("查询客户C001在2030年1月的交易汇总")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["error"])
        self.assertEqual(body["rows"], [])

    def test_dangerous_sql_rejected_and_database_untouched(self) -> None:
        self._override_pipeline(sql_generator=DangerousGenerator())
        response = self._post("删除客户表")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "SQL_REJECTED")

        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM customer_info"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 3)

    def test_query_timeout_returns_structured_504(self) -> None:
        self._override_pipeline(database_executor=TimeoutExecutor())
        response = self._post("查询有效客户数量")
        self.assertEqual(response.status_code, 504)
        body = response.json()
        self.assertEqual(body["error"]["code"], "QUERY_TIMEOUT")
        self.assertTrue(body["error"]["retryable"])

    def test_missing_database_returns_structured_503(self) -> None:
        app.dependency_overrides[self.get_query_pipeline] = lambda: build_pipeline(
            Path(self.tempdir.name) / "missing.db"
        )
        response = self._post("查询有效客户数量")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_UNAVAILABLE")

    def test_error_responses_do_not_leak_internals(self) -> None:
        self._override_pipeline(database_executor=TimeoutExecutor())
        response = self._post("查询有效客户数量")
        lowered = response.text.lower()
        for forbidden in ("traceback", "sqlite", 'file "'):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认通过**

```powershell
.venv\Scripts\python.exe -m unittest tests.test_evaluation_special_cases -v
```

Expected: `OK`（8 tests）。若 `test_out_of_range_period_returns_empty_result_not_error` 因 rows 形状失败（例如返回聚合零行 `[["C001", 0, ...]]`），把断言放宽为：`error` 为 None 且（`rows == []` 或 `rows[0][1] == 0`），并在 commit message 里注明按实际行为校准。

- [ ] **Step 3: Commit**

```powershell
git add tests/test_evaluation_special_cases.py
git commit -m "test: 固定专项测试用例库（边界/安全/超时/无数据/不泄漏）"
```

---

### Task 13: 文档、CHANGELOG 与全量验证

**Files:**
- Create: `evaluation/README.md`
- Modify: `CHANGELOG.md`（顶部新增条目；此文件在 CODEOWNERS 管控内，PR 需 @Koifufu515 审）

- [ ] **Step 1: 写 evaluation/README.md**

```markdown
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
```

- [ ] **Step 2: 更新 CHANGELOG.md**

在现有条目上方按仓库既有格式新增（先 `Read` CHANGELOG.md 看现有格式再写）：

```markdown
- test: 新增官方题库批量评测框架（evaluation/），含受控题库提取、批量Runner、
  标准化判分、第一层归因、专项用例库与版本回归对比；受控资产仅存
  data/private/evaluation/。
```

- [ ] **Step 3: 全量验证（CONTRIBUTING 四连）**

```powershell
$env:PYTHONPATH = "backend;."
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m compileall -q backend frontend tests scripts evaluation
.venv\Scripts\python.exe -m unittest discover -s tests -v 2>&1 | Select-Object -Last 5
$env:PYTHONPATH = "backend"
.venv\Scripts\python.exe -m app.adapters.database.init_db
```

Expected: `No broken requirements found.`；compileall 无输出；unittest `OK`（87 + 新增约 39 = 126 上下）；init_db 打印 Initialized。

- [ ] **Step 4: 安全终检（提交前必须）**

```powershell
git status --short
git diff --cached --stat
rg -n "农商行" evaluation tests scripts --glob "*.py" | rg -v "测试省"
```

Expected: 变更列表无 `data/private/`、无 `.env`；最后一条 rg **零输出**（代码中不存在任何非虚构机构名）。

- [ ] **Step 5: Commit**

```powershell
git add evaluation/README.md CHANGELOG.md
git commit -m "docs: 评测框架使用说明与CHANGELOG条目"
```

- [ ] **Step 6: 推送与 PR（由用户执行）**

提示用户：`git push -u origin test/official-evaluation-framework`，PR 标题 `test: 建立官方题库批量评测与版本回归框架`，关联 Issue #6；PR 前确认 `fix/windows-sqlite-connection-close` 已单独提 PR 并合并（否则本 PR 会带上该 fix 提交，需在描述中说明）。

---

## Self-Review 记录

- **Spec 覆盖**：目录结构（T2-T11）、方案 A HTTP（T9/T11）、提取与守卫（T4）、标准化（T5）、判分与诚实兜底（T6）、异常题单列（T6/T11 `--anomaly-file`）、归因表含 SQL_REJECTED/result_mismatch（T7）、断点续跑与冒烟参数（T9/T11）、聚合与脱敏摘要（T8）、版本对比（T10）、专项用例（T12）、公开/受控边界（T4 守卫 + T13 安全终检）——spec 第 1-10 节均有对应任务。
- **占位符扫描**：所有代码块完整可运行；T12 Step 2 的"放宽断言"给出了确切的替代断言，非 TBD。
- **类型一致性**：`EvalRecord.total_row_count`（T2 定义，T9 使用）、`Number.kind` 取值（T5 定义，T6 `_has_match` 使用）、`RunContext` 字段（T9 定义，T11 构造）已逐一核对一致；`load_questions(partitions=set)` 与 CLI `PARTITION_CHOICES` 映射一致（TST 而非 TEST）。
