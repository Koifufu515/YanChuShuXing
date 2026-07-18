from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation.models import SCORE_CORRECT, EvalRecord
from evaluation.reporting import percentile


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
    old_latencies_paired: list[int] = []
    new_latencies_paired: list[int] = []

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
            old_latencies_paired.append(before.elapsed_ms)
            new_latencies_paired.append(after.elapsed_ms)

    old_part = _bucket_rate(old, lambda r: r.partition)
    new_part = _bucket_rate(new, lambda r: r.partition)
    old_diff = _bucket_rate(old, lambda r: r.difficulty)
    new_diff = _bucket_rate(new, lambda r: r.difficulty)
    old_route = _bucket_rate(old, lambda r: r.route or "UNKNOWN")
    new_route = _bucket_rate(new, lambda r: r.route or "UNKNOWN")

    if old_latencies_paired:
        p50_old = percentile(old_latencies_paired, 0.50)
        p50_new = percentile(new_latencies_paired, 0.50)
        p95_old = percentile(old_latencies_paired, 0.95)
        p95_new = percentile(new_latencies_paired, 0.95)
        latency_percentiles = {
            "p50": {
                "old": p50_old,
                "new": p50_new,
                "delta": p50_new - p50_old if p50_old is not None and p50_new is not None else None,
            },
            "p95": {
                "old": p95_old,
                "new": p95_new,
                "delta": p95_new - p95_old if p95_old is not None and p95_new is not None else None,
            },
        }
    else:
        latency_percentiles = {
            "p50": {"old": None, "new": None, "delta": None},
            "p95": {"old": None, "new": None, "delta": None},
        }

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
        "rate_delta_by_partition": {
            k: new_part[k] - old_part[k]
            for k in set(old_part) & set(new_part)
        },
        "rate_delta_by_difficulty": {
            k: new_diff[k] - old_diff[k]
            for k in set(old_diff) & set(new_diff)
        },
        "rate_delta_by_route": {
            k: new_route[k] - old_route[k]
            for k in set(old_route) & set(new_route)
        },
        "latency_percentiles": latency_percentiles,
    }


def to_markdown(result: dict[str, Any], old_run_id: str, new_run_id: str) -> str:
    latency = result["mean_latency_delta_ms"]
    p50 = result["latency_percentiles"]["p50"]
    p95 = result["latency_percentiles"]["p95"]

    p50_old = p50["old"] if p50["old"] is not None else "N/A"
    p50_new = p50["new"] if p50["new"] is not None else "N/A"
    p50_delta = p50["delta"] if p50["delta"] is not None else "N/A"
    p95_old = p95["old"] if p95["old"] is not None else "N/A"
    p95_new = p95["new"] if p95["new"] is not None else "N/A"
    p95_delta = p95["delta"] if p95["delta"] is not None else "N/A"

    lines = [
        f"# 版本回归对比（受控）：{old_run_id} -> {new_run_id}",
        "",
        f"- 共同题数：{result['shared_total']}",
        f"- 仅旧版有：{len(result['only_in_old'])} 题；仅新版有：{len(result['only_in_new'])} 题",
        f"- 正确率变化：{result['correct_rate_delta'] * 100:+.1f} 个百分点",
        f"- 平均耗时变化：{latency if latency is not None else 'N/A'} ms",
        f"- 耗时 P50：{p50_old} -> {p50_new}（Δ{p50_delta}）ms",
        f"- 耗时 P95：{p95_old} -> {p95_new}（Δ{p95_delta}）ms",
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
    if result["rate_delta_by_partition"]:
        lines.append("## 按分区正确率变化")
        for key in sorted(result["rate_delta_by_partition"]):
            delta = result["rate_delta_by_partition"][key]
            lines.append(f"- {key}: {delta * 100:+.1f} 个百分点")
        lines.append("")
    if result["rate_delta_by_difficulty"]:
        lines.append("## 按难度正确率变化")
        for key in sorted(result["rate_delta_by_difficulty"]):
            delta = result["rate_delta_by_difficulty"][key]
            lines.append(f"- {key}: {delta * 100:+.1f} 个百分点")
        lines.append("")
    return "\n".join(lines)


def _correct_rate(records: dict[str, EvalRecord]) -> float:
    if not records:
        return 0.0
    correct = sum(
        1 for record in records.values() if record.score_status == SCORE_CORRECT
    )
    return correct / len(records)


def _bucket_rate(
    records: dict[str, EvalRecord],
    key_fn: Any,
) -> dict[str, float]:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for record in records.values():
        key = key_fn(record)
        buckets[key].append(record.score_status == SCORE_CORRECT)
    return {k: sum(v) / len(v) for k, v in buckets.items()}
