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
