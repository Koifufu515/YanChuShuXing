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
