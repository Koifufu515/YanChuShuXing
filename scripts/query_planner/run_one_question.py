from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider
from app.adapters.planning.llm_query_planner import LLMQueryPlanner
from app.application.errors import InvalidProviderOutputError
from app.core.settings import Settings


DEFAULT_QUESTION = "江苏省A市农商行在2025年6月15日，各项存款余额是多少？"


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"无法读取JSON文件：{path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON文件顶层必须是对象：{path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="查询规划器单题测试")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    args = parser.parse_args()

    config_dir = PROJECT_ROOT / "config" / "query_planner"
    prompt_path = config_dir / "query_planner_prompt.md"
    schema_path = config_dir / "query_plan.schema.json"
    context_path = config_dir / "query_planner_context.json"

    prompt = prompt_path.read_text(encoding="utf-8")
    schema = load_json(schema_path)
    context = load_json(context_path)

    settings = Settings.from_env(args.env_file)
    if not settings.llm_api_key:
        raise SystemExit(
            "未读取到BANKINSIGHT_LLM_API_KEY。请配置Codespaces Secret或本地.env。"
        )

    provider = DeepSeekLLMProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    planner = LLMQueryPlanner(
        provider=provider,
        prompt=prompt,
        schema=schema,
        context=context,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=0.0,
    )

    try:
        result = planner.plan(args.question)
    except InvalidProviderOutputError as exc:
        payload = {
            "success": False,
            "stage": "json_parse",
            "error": exc.public_message,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    payload = asdict(result)
    output_dir = PROJECT_ROOT / "data" / "private" / "query_planner_runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"manual_single_{timestamp}.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n结果已保存到：{output_path.relative_to(PROJECT_ROOT)}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
