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
