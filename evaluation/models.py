from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VALID_SPLITS = frozenset({"TRAIN", "VAL", "TST"})


@dataclass(frozen=True)
class EvaluationQuestion:
    question_id: str
    split: str
    question_type: str
    difficulty: str
    question: str
    official_answer: str
    corrected_answer: str | None
    expected_answer: str
    answer_source: str


@dataclass(frozen=True)
class EvaluationPaths:
    project_root: Path
    source: Path
    run_root: Path

    @property
    def manifest(self) -> Path:
        return self.run_root / "manifest.json"

    @property
    def results(self) -> Path:
        return self.run_root / "results.jsonl"

    @property
    def summary(self) -> Path:
        return self.run_root / "summary.json"

    @property
    def failures(self) -> Path:
        return self.run_root / "failures.jsonl"
