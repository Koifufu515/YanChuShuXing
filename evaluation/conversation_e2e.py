from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.application.models import QueryCommand
from app.bootstrap.container import build_pipeline

CONVERSATION_ID = f"conv-e2e-{uuid.uuid4().hex[:8]}"

ROUNDS = [
    {
        "round": 1,
        "input": "江苏省A市农商行在2025年6月15日，各项存款余额是多少？",
        "expected_institution": "ORG001",
        "expected_metric": "各项存款余额 / ZB001",
        "expected_date": "2025-06-15",
        "expected_operation": "单值查询",
    },
    {
        "round": 2,
        "input": "换成B市农商行。",
        "expected_institution": "ORG002",
        "expected_metric": "各项存款余额（继承）",
        "expected_date": "2025-06-15（继承）",
        "expected_operation": "机构替换",
    },
    {
        "round": 3,
        "input": "改看2025年3月。",
        "expected_institution": "ORG002（继承）",
        "expected_metric": "各项存款余额（继承）",
        "expected_date": "2025-03-31",
        "expected_operation": "日期更新",
    },
    {
        "round": 4,
        "input": "刚才那个指标换成不良贷款率。",
        "expected_institution": "ORG002（继承）",
        "expected_metric": "不良贷款率 / ZB013",
        "expected_date": "2025-03-31（继承）",
        "expected_operation": "指标切换",
    },
    {
        "round": 5,
        "input": "再比较一下全省均值。",
        "expected_institution": "ORG002（继承）",
        "expected_metric": "不良贷款率（继承）",
        "expected_date": "2025-03-31（继承）",
        "expected_operation": "比较全省均值",
    },
    {
        "round": 6,
        "input": "改成排名。",
        "expected_institution": "全机构",
        "expected_metric": "不良贷款率（继承）",
        "expected_date": "2025-03-31（继承）",
        "expected_operation": "排名模式",
    },
    {
        "round": 7,
        "input": "只看后三名。",
        "expected_institution": "全机构",
        "expected_metric": "不良贷款率（继承）",
        "expected_date": "2025-03-31（继承）",
        "expected_operation": "Bottom 3",
    },
    {
        "round": 8,
        "input": "换成成本收入比。",
        "expected_institution": "全机构（继承）",
        "expected_metric": "成本收入比 / ZB030",
        "expected_date": "2025-03-31（继承）",
        "expected_operation": "指标切换",
    },
    {
        "round": 9,
        "input": "继续看A市最近一年的趋势。",
        "expected_institution": "ORG001",
        "expected_metric": "成本收入比（继承）",
        "expected_date": "时间序列",
        "expected_operation": "机构+趋势切换",
    },
    {
        "round": 10,
        "input": "总结刚才所有涉及机构的结论。",
        "expected_institution": "多机构",
        "expected_metric": "多指标",
        "expected_date": "多日期",
        "expected_operation": "上下文汇总",
    },
]


def run_conversation_e2e() -> dict[str, Any]:
    pipeline = build_pipeline()
    results: list[dict[str, Any]] = []

    print(f"Conversation ID: {CONVERSATION_ID}")
    print(f"{'='*60}")

    for spec in ROUNDS:
        round_num = spec["round"]
        question = spec["input"]

        print(f"\n[Round {round_num}/10] {question}")
        print(f"  Expected: inst={spec['expected_institution']} "
              f"metric={spec['expected_metric']} date={spec['expected_date']}")

        t0 = time.perf_counter()
        try:
            cmd = QueryCommand(
                question=question,
                user_id="eval_e2e",
                conversation_id=CONVERSATION_ID,
                request_id=f"conv-round{round_num}-{uuid.uuid4().hex[:6]}",
            )
            outcome = pipeline.run(cmd)
        except Exception as exc:
            results.append({
                "round": round_num,
                "input": question,
                "status": "exception",
                "error": f"{type(exc).__name__}: {exc}",
                "duration_ms": (time.perf_counter() - t0) * 1000,
            })
            print(f"  EXCEPTION: {exc}")
            break

        duration_ms = (time.perf_counter() - t0) * 1000

        has_error = outcome.error is not None
        status = "success" if not has_error else f"error:{outcome.error.code}"

        row_count = len(outcome.rows) if outcome.rows else 0
        summary = (outcome.summary or "")[:200]

        result_entry = {
            "round": round_num,
            "input": question,
            "status": status,
            "sql": outcome.sql,
            "columns": outcome.columns,
            "row_count": row_count,
            "summary": outcome.summary,
            "duration_ms": round(duration_ms, 0),
            "error": {"code": outcome.error.code, "message": outcome.error.message} if outcome.error else None,
        }
        results.append(result_entry)

        status_icon = "OK" if status == "success" else "FAIL"
        print(f"  [{status_icon}] {duration_ms:.0f}ms rows={row_count}")
        if summary:
            print(f"  Summary: {summary}")

    failed_at = None
    for r in results:
        if r["status"] != "success":
            failed_at = r["round"]
            break

    report = {
        "conversation_id": CONVERSATION_ID,
        "total_rounds": len(results),
        "passed_rounds": sum(1 for r in results if r["status"] == "success"),
        "failed_rounds": sum(1 for r in results if r["status"] != "success"),
        "first_failure_round": failed_at,
        "results": results,
    }

    return report


def main() -> int:
    report = run_conversation_e2e()

    print(f"\n{'='*60}")
    print("CONVERSATION E2E REPORT")
    print(f"{'='*60}")
    print(f"  Total rounds: {report['total_rounds']}")
    print(f"  Passed: {report['passed_rounds']}")
    print(f"  Failed: {report['failed_rounds']}")
    print(f"  First failure at round: {report['first_failure_round'] or 'N/A'}")

    output_path = Path(__file__).resolve().parents[1] / "data" / "private" / "evaluation" / "conversation_e2e.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nReport saved to: {output_path}")

    return 0 if report["failed_rounds"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
