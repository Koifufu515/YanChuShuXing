from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider
from app.application.errors import ApplicationError
from app.application.models import QueryPlanPhaseTelemetry, QueryPlanResult


def _load_settings(env_file: Path) -> Any:
    from app.core.settings import Settings

    return Settings.from_env(env_file)


def _usage_payload(phase: QueryPlanPhaseTelemetry | None) -> dict[str, Any] | None:
    if phase is None:
        return None
    usage = phase.llm.usage
    cache_total = usage.prompt_cache_hit_tokens + usage.prompt_cache_miss_tokens
    cache_hit_rate = (
        round(usage.prompt_cache_hit_tokens / cache_total, 6)
        if cache_total
        else None
    )
    output_tokens_per_second = (
        round(usage.completion_tokens / (phase.llm.latency_ms / 1000), 3)
        if phase.llm.latency_ms > 0
        else None
    )
    return {
        "prompt_build_ms": phase.prompt_build_ms,
        "llm_latency_ms": phase.llm.latency_ms,
        "parse_ms": phase.parse_ms,
        "validation_ms": phase.validation_ms,
        "schema_validation_ms": phase.schema_validation_ms,
        "business_validation_ms": phase.business_validation_ms,
        "request_body_bytes": phase.llm.request_body_bytes,
        "response_body_bytes": phase.llm.response_body_bytes,
        "prompt_tokens": usage.prompt_tokens,
        "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
        "completion_tokens": usage.completion_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
        "cache_hit_rate": cache_hit_rate,
        "output_tokens_per_second": output_tokens_per_second,
    }


def build_profile(result: QueryPlanResult, elapsed_ms: float) -> dict[str, Any]:
    operations = result.query_plan.get("operations")
    operation_count = len(operations) if isinstance(operations, list) else 0
    status = result.query_plan.get("status")
    status_code = status.get("code") if isinstance(status, dict) else None
    return {
        "success": result.success,
        "model": result.model,
        "thinking_mode": "disabled",
        "repair_attempted": result.repair_attempted,
        "query_plan_status": status_code,
        "operation_count": operation_count,
        "elapsed_ms": round(elapsed_ms, 3),
        "planning_total_ms": result.performance.total_planning_ms,
        "llm_total_ms": result.latency_ms,
        "unattributed_ms": result.performance.unattributed_ms,
        "deterministic_executor_ms": None,
        "initial": _usage_payload(result.performance.initial),
        "repair": _usage_payload(result.performance.repair),
    }


def build_failure_profile(exc: ApplicationError, elapsed_ms: float) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": exc.code,
        "error": exc.public_message,
        "elapsed_ms": round(elapsed_ms, 3),
    }


def summarize_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [profile for profile in profiles if profile.get("success")]
    elapsed = [float(profile["elapsed_ms"]) for profile in successful]
    return {
        "repeat": len(profiles),
        "successful_runs": len(successful),
        "failed_runs": len(profiles) - len(successful),
        "average_elapsed_ms": round(statistics.fmean(elapsed), 3) if elapsed else None,
        "min_elapsed_ms": round(min(elapsed), 3) if elapsed else None,
        "max_elapsed_ms": round(max(elapsed), 3) if elapsed else None,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = ["言出数行：单题查询规划性能报告"]
    summary = report["summary"]
    lines.extend(
        [
            f"重复次数：{summary['repeat']}",
            f"成功/失败：{summary['successful_runs']}/{summary['failed_runs']}",
            f"平均脚本规划耗时：{summary['average_elapsed_ms']} ms",
        ]
    )
    for index, run in enumerate(report["runs"], start=1):
        lines.append(f"\n第 {index} 次")
        if not run.get("success"):
            lines.append(f"状态：失败（{run.get('error_code')}）")
            lines.append(f"错误：{run.get('error')}")
            continue
        lines.extend(
            [
                f"模型：{run['model']}",
                f"思考模式：{run['thinking_mode']}",
                f"是否触发修复：{'是' if run['repair_attempted'] else '否'}",
                f"查询计划状态：{run['query_plan_status']}",
                f"操作节点数量：{run['operation_count']}",
                f"规划总耗时：{run['planning_total_ms']} ms",
                f"LLM 总耗时：{run['llm_total_ms']} ms",
                f"其他未归属耗时：{run['unattributed_ms']} ms",
                "确定性执行器耗时：未执行（本报告仅运行正式查询规划器）",
            ]
        )
        for label, key in (("初次", "initial"), ("修复", "repair")):
            phase = run[key]
            if phase is None:
                lines.append(f"{label}阶段：未触发")
                continue
            lines.extend(
                [
                    f"{label} LLM 耗时：{phase['llm_latency_ms']} ms",
                    f"{label}解析/Schema/业务校验：{phase['parse_ms']}/"
                    f"{phase['schema_validation_ms']}/{phase['business_validation_ms']} ms",
                    f"{label} Prompt Token：{phase['prompt_tokens']}",
                    f"{label}缓存命中/未命中：{phase['prompt_cache_hit_tokens']}/"
                    f"{phase['prompt_cache_miss_tokens']}",
                    f"{label} Completion/Reasoning/总 Token："
                    f"{phase['completion_tokens']}/{phase['reasoning_tokens']}/"
                    f"{phase['total_tokens']}",
                    f"{label}请求/响应字节数：{phase['request_body_bytes']}/"
                    f"{phase['response_body_bytes']}",
                    f"{label}缓存命中率：{phase['cache_hit_rate']}",
                    f"{label}输出 Token 生成速率：{phase['output_tokens_per_second']}",
                ]
            )
    return "\n".join(lines) + "\n"


def _write_output(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成单题查询规划脱敏性能报告")
    parser.add_argument("--question", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--text-output", type=Path)
    args = parser.parse_args(argv)
    if args.repeat < 1 or args.warmup < 0:
        parser.error("--repeat 必须至少为 1，--warmup 不能为负数。")

    settings = _load_settings(args.env_file)
    if not settings.llm_api_key:
        print(
            "未读取到 BANKINSIGHT_LLM_API_KEY；无法执行真实性能测试。",
            file=sys.stderr,
        )
        return 2
    from app.bootstrap.container import _build_query_planner

    planner = _build_query_planner(
        provider=DeepSeekLLMProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        ),
        settings=settings,
    )

    for _ in range(args.warmup):
        try:
            planner.plan(args.question)
        except ApplicationError as exc:
            print(f"预热失败（{exc.code}）：{exc.public_message}", file=sys.stderr)
            return 1

    profiles: list[dict[str, Any]] = []
    for _ in range(args.repeat):
        started = time.perf_counter()
        try:
            result = planner.plan(args.question)
        except ApplicationError as exc:
            profiles.append(
                build_failure_profile(exc, (time.perf_counter() - started) * 1000)
            )
        else:
            profiles.append(
                build_profile(result, (time.perf_counter() - started) * 1000)
            )

    report = {"summary": summarize_profiles(profiles), "runs": profiles}
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    text_report = render_text(report)
    _write_output(args.json_output, json_text)
    _write_output(args.text_output, text_report)
    print(text_report, end="")
    return 0 if all(profile.get("success") for profile in profiles) else 1


if __name__ == "__main__":
    raise SystemExit(main())
