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
