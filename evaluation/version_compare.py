from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation.scorer import read_jsonl, latest_records_by_question


def load_scored_by_question(run_dir: Path) -> dict[str, dict[str, Any]]:
    scored_path = run_dir / "scored_results.jsonl"
    if not scored_path.is_file():
        results_path = run_dir / "results.jsonl"
        if not results_path.is_file():
            raise FileNotFoundError(f"Run directory missing results: {run_dir}")
        records = read_jsonl(results_path)
        return latest_records_by_question(records)
    records = read_jsonl(scored_path)
    return latest_records_by_question(records)


def compare_runs(
    old_run_dir: Path,
    new_run_dir: Path,
    old_commit: str = "",
    new_commit: str = "",
) -> dict[str, Any]:
    old_records = load_scored_by_question(old_run_dir)
    new_records = load_scored_by_question(new_run_dir)

    all_ids = sorted(set(old_records) | set(new_records))
    if not all_ids:
        raise ValueError("Both run directories have no scored records.")

    improved: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    persistent_failures: list[dict[str, Any]] = []
    new_errors: list[dict[str, Any]] = []
    unchanged: int = 0

    for qid in all_ids:
        old = old_records.get(qid, {})
        new = new_records.get(qid, {})

        old_status = old.get("comparison_status") or "not_scored"
        new_status = new.get("comparison_status") or "not_scored"
        old_run = old.get("run_status") or ""
        new_run = new.get("run_status") or ""

        entry = {
            "question_id": qid,
            "difficulty": new.get("difficulty") or old.get("difficulty", ""),
            "question_type": new.get("question_type") or old.get("question_type", ""),
            "old_comparison_status": old_status,
            "new_comparison_status": new_status,
            "old_run_status": old_run,
            "new_run_status": new_run,
            "old_duration_ms": old.get("duration_ms"),
            "new_duration_ms": new.get("duration_ms"),
        }

        if old_status != "pass" and new_status == "pass":
            entry["reason"] = _improvement_reason(old, new)
            improved.append(entry)
        elif old_status == "pass" and new_status != "pass":
            entry["reason"] = _regression_reason(new)
            regressed.append(entry)
        elif old_status != "pass" and new_status != "pass":
            entry["reason"] = _persistent_reason(new)
            persistent_failures.append(entry)
        else:
            unchanged += 1

        if new_status != "pass" and _is_new_system_error(old, new):
            new_errors.append(entry)

    old_durations = [
        r.get("duration_ms") for r in old_records.values()
        if isinstance(r.get("duration_ms"), (int, float))
    ]
    new_durations = [
        r.get("duration_ms") for r in new_records.values()
        if isinstance(r.get("duration_ms"), (int, float))
    ]

    old_pass = sum(1 for r in old_records.values() if r.get("comparison_status") == "pass")
    new_pass = sum(1 for r in new_records.values() if r.get("comparison_status") == "pass")

    old_total = max(len(old_records), 1)
    new_total = max(len(new_records), 1)

    timing = {
        "old": _timing_stats(old_durations),
        "new": _timing_stats(new_durations),
    }

    recommendation = _recommend(regressed, persistent_failures, new_errors, old_pass, new_pass)

    return {
        "old_run_dir": str(old_run_dir.resolve()),
        "new_run_dir": str(new_run_dir.resolve()),
        "old_commit": old_commit,
        "new_commit": new_commit,
        "old_total": old_total,
        "new_total": new_total,
        "old_pass": old_pass,
        "new_pass": new_pass,
        "old_pass_rate": round(old_pass / old_total, 4),
        "new_pass_rate": round(new_pass / new_total, 4),
        "improved_count": len(improved),
        "regressed_count": len(regressed),
        "persistent_failure_count": len(persistent_failures),
        "unchanged_count": unchanged,
        "new_error_count": len(new_errors),
        "improved": improved,
        "regressed": regressed,
        "persistent_failures": persistent_failures,
        "new_errors": new_errors,
        "timing": timing,
        "recommendation": recommendation,
    }


def _improvement_reason(old: Mapping[str, Any], new: Mapping[str, Any]) -> str:
    old_comp = old.get("comparison") or {}
    old_reason = old_comp.get("reason", old.get("comparison_status", ""))
    return f"旧版:{old_reason} → 新版通过"


def _regression_reason(record: Mapping[str, Any]) -> str:
    comp = record.get("comparison") or {}
    if comp.get("mode") == "executable_answer":
        return f"运行失败: {record.get('run_status', 'unknown')}"
    active = comp.get("active_components", [])
    components = comp.get("components") or {}
    failed = [
        name for name in active
        if not (components.get(name) or {}).get("passed", True)
    ]
    if failed:
        return f"组件失败: {', '.join(failed)}"
    return comp.get("reason", "未知原因")


def _persistent_reason(record: Mapping[str, Any]) -> str:
    comp = record.get("comparison") or {}
    if comp.get("mode") == "executable_answer":
        return f"持续运行失败: {record.get('run_status', 'unknown')}"
    return comp.get("reason", "持续失败")


def _is_new_system_error(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    old_run = old.get("run_status") or ""
    new_run = new.get("run_status") or ""
    old_was_ok = old_run in ("success", "")
    new_is_error = new_run in ("failed", "exception")
    return bool(old_was_ok and new_is_error)


def _timing_stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "mean": round(statistics.fmean(values), 3),
        "p50": round(ordered[n // 2], 3),
        "p95": round(ordered[int(n * 0.95)], 3) if n > 1 else round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


def _recommend(
    regressed: list[dict[str, Any]],
    persistent: list[dict[str, Any]],
    new_errors: list[dict[str, Any]],
    old_pass: int,
    new_pass: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    if regressed:
        reasons.append(f"{len(regressed)} question(s) regressed")
    if len(new_errors) > len(regressed):
        reasons.append(f"{len(new_errors)} new system error(s)")

    if not regressed and not reasons:
        if new_pass < old_pass:
            return {"action": "review", "reasons": ["pass count decreased despite no clear regressions"]}
        return {"action": "allow_merge", "reasons": ["no regressions, no new errors"]}

    return {"action": "block_merge", "reasons": reasons}


def format_markdown_report(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 版本评测对比报告")
    lines.append("")
    lines.append("## 基线")
    lines.append("")
    lines.append(f"- 旧提交: {result['old_commit'] or 'N/A'}")
    lines.append(f"- 旧 run 目录: {result['old_run_dir']}")
    lines.append(f"- 新提交: {result['new_commit'] or 'N/A'}")
    lines.append(f"- 新 run 目录: {result['new_run_dir']}")
    lines.append("")

    lines.append("## 汇总")
    lines.append("")
    lines.append("| 指标 | 旧版本 | 新版本 | 变化 |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| 通过题数 | {result['old_pass']} | {result['new_pass']} | {_delta(result['new_pass'], result['old_pass'])} |")
    lines.append(f"| 通过率 | {result['old_pass_rate']} | {result['new_pass_rate']} | {_delta_f(result['new_pass_rate'], result['old_pass_rate'])} |")

    t = result["timing"]
    for label, key in [("平均耗时ms", "mean"), ("P50 ms", "p50"), ("P95 ms", "p95"), ("最大耗时ms", "max")]:
        old_v = t["old"].get(key)
        new_v = t["new"].get(key)
        if old_v is not None and new_v is not None:
            lines.append(f"| {label} | {old_v} | {new_v} | {_delta_f(new_v, old_v)} |")

    lines.append("")
    lines.append("## 改善项")
    lines.append("")
    if result["improved"]:
        lines.append("| 题号 | 旧状态 | 新状态 | 归因 |")
        lines.append("|---|---|---|---|")
        for item in result["improved"]:
            lines.append(f"| {item['question_id']} | {item['old_comparison_status']} | pass | {item['reason']} |")
    else:
        lines.append("无")
    lines.append("")

    lines.append("## 退化项")
    lines.append("")
    if result["regressed"]:
        lines.append("| 题号 | 旧状态 | 新状态 | 阻塞原因 |")
        lines.append("|---|---|---|---|")
        for item in result["regressed"]:
            lines.append(f"| {item['question_id']} | pass | {item['new_comparison_status']} | {item['reason']} |")
    else:
        lines.append("无")
    lines.append("")

    lines.append("## 持续失败与异常题")
    lines.append("")
    if result["persistent_failures"]:
        lines.append("| 题号 | 状态 | 第一层归因 |")
        lines.append("|---|---|---|")
        for item in result["persistent_failures"]:
            lines.append(f"| {item['question_id']} | {item['new_comparison_status']} | {item['reason']} |")
    else:
        lines.append("无")
    lines.append("")

    lines.append("## 新增系统错误")
    lines.append("")
    if result["new_errors"]:
        lines.append("| 题号 | 旧运行状态 | 新运行状态 |")
        lines.append("|---|---|---|")
        for item in result["new_errors"]:
            lines.append(f"| {item['question_id']} | {item['old_run_status']} | {item['new_run_status']} |")
    else:
        lines.append("无")
    lines.append("")

    rec = result["recommendation"]
    lines.append("## 发布建议")
    lines.append("")
    action_labels = {"allow_merge": "允许合并", "block_merge": "阻塞合并", "review": "需人工审核"}
    lines.append(f"- 建议: **{action_labels.get(rec['action'], rec['action'])}**")
    for reason in rec["reasons"]:
        lines.append(f"  - {reason}")
    lines.append("")

    return "\n".join(lines)


def _delta(new: int, old: int) -> str:
    diff = new - old
    if diff > 0:
        return f"+{diff}"
    if diff < 0:
        return str(diff)
    return "0"


def _delta_f(new: float, old: float) -> str:
    diff = round(new - old, 4)
    if diff > 0:
        return f"+{diff}"
    if diff < 0:
        return str(diff)
    return "0"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two evaluation run directories")
    parser.add_argument("--old-run-dir", type=Path, required=True)
    parser.add_argument("--new-run-dir", type=Path, required=True)
    parser.add_argument("--old-commit", default="")
    parser.add_argument("--new-commit", default="")
    parser.add_argument("--output", type=Path, help="Write Markdown report to file")
    parser.add_argument("--json-output", type=Path, help="Write JSON report to file")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = compare_runs(
        args.old_run_dir,
        args.new_run_dir,
        args.old_commit,
        args.new_commit,
    )

    if args.json_output:
        import json as _json

        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            _json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    if args.output:
        md = format_markdown_report(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(md, encoding="utf-8")
        print(f"Markdown report written to {args.output}")
    else:
        print(format_markdown_report(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
