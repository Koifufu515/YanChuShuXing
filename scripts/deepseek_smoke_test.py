from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.context.yaml_resolver import YAMLContextResolver
from app.adapters.database.sqlite_executor import SQLiteExecutor
from app.adapters.generation.llm_generator import LLMSQLGenerator
from app.adapters.generation.hybrid_generator import HybridSQLGenerator
from app.adapters.generation.rule_generator import RuleSQLGenerator
from app.adapters.formatting.template_formatter import TemplateResultFormatter
from app.adapters.llm.deepseek_provider import DeepSeekLLMProvider
from app.adapters.safety.sqlglot_checker import SQLGlotSafetyChecker
from app.application.errors import ApplicationError
from app.application.models import UserContext
from app.core.settings import Settings


QUESTIONS = (
    "查询有效客户数量",
    "查询客户C001的账户余额",
    "查询客户C001在2026年6月的交易汇总",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="言出数行 DeepSeek 冒烟测试")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--question", action="append", dest="questions")
    args = parser.parse_args()

    settings = Settings.from_env(args.env_file)
    if not settings.llm_api_key:
        print("SKIPPED: BANKINSIGHT_LLM_API_KEY 未配置。")
        return 0

    resolver = YAMLContextResolver(
        PROJECT_ROOT / "config" / "schema.yml",
        PROJECT_ROOT / "config" / "metrics.yml",
    )
    provider = DeepSeekLLMProvider(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
    )
    llm_generator = LLMSQLGenerator(
        provider,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        configured_mode=settings.generator_mode,
        provider_name=settings.llm_provider,
    )
    rule_generator = RuleSQLGenerator(configured_mode=settings.generator_mode)
    if settings.generator_mode == "rule":
        generator = rule_generator
    elif settings.generator_mode == "llm":
        generator = llm_generator
    else:
        generator = HybridSQLGenerator(
            llm_generator,
            rule_generator,
            provider_name=settings.llm_provider,
            model=settings.llm_model,
        )
    safety_checker = SQLGlotSafetyChecker()
    executor = SQLiteExecutor(PROJECT_ROOT / "data" / "processed" / "bankinsight.db")
    formatter = TemplateResultFormatter()

    failures = 0
    for question in args.questions or QUESTIONS:
        print(f"\nQUESTION: {question}")
        context = resolver.resolve(question)
        try:
            generated = generator.generate(question, context)
        except ApplicationError as error:
            print(
                json.dumps(
                    {"error_code": error.code, "message": error.public_message},
                    ensure_ascii=False,
                )
            )
            failures += 1
            continue

        safety = safety_checker.validate(
            generated.sql,
            UserContext(
                user_id="deepseek_smoke",
                allowed_tables=context.allowed_tables,
                denied_columns=context.denied_columns,
            ),
        )
        result_payload = None
        summary = None
        if safety.allowed:
            result = executor.execute_query(
                generated.sql, generated.parameters, max_rows=100
            )
            result_payload = {
                "columns": result.columns,
                "rows": result.rows,
                "duration_ms": result.duration_ms,
            }
            summary = formatter.format(question, result).summary
        else:
            failures += 1

        print(
            json.dumps(
                {
                    "configured_mode": settings.generator_mode,
                    "executed_generator": (
                        generated.metadata.executed_generator
                        if generated.metadata
                        else generated.generator_name
                    ),
                    "metadata": asdict(generated.metadata) if generated.metadata else None,
                    "sql": generated.sql,
                    "parameters": generated.parameters,
                    "safety": {
                        "allowed": safety.allowed,
                        "error_code": safety.error_code,
                        "referenced_tables": safety.referenced_tables,
                    },
                    "result": result_payload,
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
