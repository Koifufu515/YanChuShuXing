from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from frontend.api_client import APIConnectionError, BankInsightClient


QUESTIONS = (
    "查询有效客户数量",
    "查询客户C001的账户余额",
    "查询客户C001在2026年6月的交易汇总",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="言出数行查询稳定性检查")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--iterations", type=int, default=60)
    args = parser.parse_args()

    client = BankInsightClient(args.base_url, timeout_seconds=70)
    for index in range(args.iterations):
        question = QUESTIONS[index % len(QUESTIONS)]
        try:
            result = client.query(question, conversation_id="stability_check")
        except APIConnectionError as error:
            print(f"FAILED iteration={index + 1}: {error}")
            return 1
        error = result.payload.get("error")
        if error:
            print(f"FAILED iteration={index + 1}: {error.get('code')}")
            return 1
        print(
            f"PASS {index + 1}/{args.iterations} "
            f"question={question} elapsed_ms={result.elapsed_ms}"
        )
    print(f"STABILITY_CHECK=PASS iterations={args.iterations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
