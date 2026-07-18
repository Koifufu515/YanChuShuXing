from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from evaluation.models import (
    SCORE_CORRECT,
    SCORE_EXCLUDED_ANOMALY,
    SCORE_NEEDS_MANUAL_REVIEW,
    SCORE_NOT_SCORED_SYSTEM_ERROR,
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
        if status
        not in {SCORE_NEEDS_MANUAL_REVIEW, SCORE_EXCLUDED_ANOMALY, SCORE_NOT_SCORED_SYSTEM_ERROR}
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
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
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


def percentile(values: list[int], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(ratio * len(ordered)) - 1))
    return ordered[index]
