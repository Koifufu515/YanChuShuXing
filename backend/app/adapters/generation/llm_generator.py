from __future__ import annotations

import json
from dataclasses import asdict

import yaml

from app.application.errors import (
    ClarificationRequiredError,
    InvalidProviderOutputError,
    InvalidSemanticOutputError,
    InvalidSQLOutputError,
    UnsupportedMetricError,
)
from app.application.models import (
    BusinessSemantic,
    GeneratedSQL,
    JsonScalar,
    LLMRequest,
    QueryMetadata,
    QueryContext,
    SemanticMetadata,
)
from app.ports.llm_provider import LLMProvider


SEMANTIC_SYSTEM_PROMPT = """你是银行经营分析语义解析器。只返回一个合法 JSON 对象，不得使用 Markdown 代码围栏或解释文字。不得创造上下文中不存在的指标。business_domain 必须使用所选指标定义中的 theme；intent 必须是具体稳定的任务名，例如 active_customer_count、customer_account_balance、monthly_transaction_summary，不得使用 query_task 等泛化名称。自然月交易汇总应识别为 business_domain=transaction、intent=monthly_transaction_summary。必须严格遵守字段类型：metrics、dimensions、sort 必须是 JSON 数组（无内容时返回 []）；filters 必须是 JSON 对象（无条件时返回 {}）；time_range 可以是对象或 null；limit 必须是整数或 null；clarification_required 必须是布尔值；confidence 必须是0到1之间的数字。"""

SQL_SYSTEM_PROMPT = """你是 SQLite 只读 SQL 生成器。只返回一个合法 JSON 对象，不得使用 Markdown 代码围栏或解释文字。只允许一条 SELECT 或 CTE；只能使用给定表字段和指标口径；动态值使用命名参数；禁止写操作、PRAGMA 和多语句。为兼容结果解释器：有效客户数列别名必须是 customer_count；客户账户余额必须同时返回 customer_id 和别名 account_balance；交易汇总必须返回 customer_id、transaction_count、total_in、total_out、net_amount。"""

REQUIRED_SEMANTIC_FIELDS = {
    "intent",
    "business_domain",
    "metrics",
    "dimensions",
    "filters",
    "time_range",
    "sort",
    "limit",
    "clarification_required",
    "clarification_question",
}


class LLMSQLGenerator:
    name = "llm"

    def __init__(
        self,
        provider: LLMProvider,
        temperature: float = 0.0,
        timeout_seconds: float = 20.0,
        configured_mode: str = "llm",
        provider_name: str = "deepseek",
    ) -> None:
        self.provider = provider
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.configured_mode = configured_mode
        self.provider_name = provider_name

    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        semantic, semantic_model, semantic_latency = self.parse_semantics(
            question, context
        )
        generated, sql_model, sql_latency = self.generate_from_semantics(
            question, semantic, context
        )
        model = sql_model or semantic_model
        return GeneratedSQL(
            sql=generated.sql,
            parameters=generated.parameters,
            generator_name=f"llm:{model}",
            warnings=generated.warnings,
            metadata=QueryMetadata(
                configured_mode=self.configured_mode,
                executed_generator="llm",
                rule_matched=False,
                route="LLM",
                provider=self.provider_name,
                model=model,
                llm_latency_ms=round(semantic_latency + sql_latency, 2),
                semantic=SemanticMetadata(
                    intent=semantic.intent,
                    business_domain=semantic.business_domain,
                    metrics=semantic.metrics,
                    dimensions=semantic.dimensions,
                    filters=semantic.filters,
                    time_range=semantic.time_range,
                    confidence=semantic.confidence,
                ),
            ),
        )

    def parse_semantics(
        self, question: str, context: QueryContext
    ) -> tuple[BusinessSemantic, str, float]:
        response = self.provider.complete(
            LLMRequest(
                system_prompt=SEMANTIC_SYSTEM_PROMPT,
                user_prompt=self._semantic_prompt(question, context),
                temperature=self.temperature,
                timeout_seconds=self.timeout_seconds,
            )
        )
        payload = _strict_json_object(
            response.text, "业务语义", InvalidSemanticOutputError
        )
        semantic = _parse_semantic(payload, _metric_ids(context.metric_context))
        if semantic.clarification_required:
            question_text = semantic.clarification_question or "请补充查询条件。"
            raise ClarificationRequiredError(question_text)
        return semantic, response.model, response.latency_ms

    def generate_from_semantics(
        self,
        question: str,
        semantic: BusinessSemantic,
        context: QueryContext,
    ) -> tuple[GeneratedSQL, str, float]:
        response = self.provider.complete(
            LLMRequest(
                system_prompt=SQL_SYSTEM_PROMPT,
                user_prompt=self._sql_prompt(question, semantic, context),
                temperature=self.temperature,
                timeout_seconds=self.timeout_seconds,
            )
        )
        payload = _strict_json_object(response.text, "SQL", InvalidSQLOutputError)
        generated = _parse_generated_sql(payload)
        return generated, response.model, response.latency_ms

    @staticmethod
    def _semantic_prompt(question: str, context: QueryContext) -> str:
        return f"""用户问题：{question}

可用指标上下文：
{context.metric_context}

可用 Schema 上下文：
{context.schema_context}

严格按以下结构输出，不得改变字段类型：
{{
  "intent": "query_task",
  "business_domain": "customer",
  "metrics": [],
  "dimensions": [],
  "filters": {{}},
  "time_range": null,
  "sort": [],
  "limit": null,
  "clarification_required": false,
  "clarification_question": null,
  "confidence": 0.95
}}"""

    @staticmethod
    def _sql_prompt(
        question: str, semantic: BusinessSemantic, context: QueryContext
    ) -> str:
        semantic_json = json.dumps(asdict(semantic), ensure_ascii=False)
        allowed_tables = ", ".join(sorted(context.allowed_tables))
        return f"""用户原始问题：{question}

业务语义：{semantic_json}

Schema Context：
{context.schema_context}

Metric Context：
{context.metric_context}

允许表：{allowed_tables}
禁止字段：{', '.join(sorted(context.denied_columns)) or '无'}
SQL 方言：SQLite

稳定结果列约定：
- 有效客户数：customer_count
- 客户账户余额：customer_id, account_balance
- 交易汇总：customer_id, transaction_count, total_in, total_out, net_amount

请输出字段：sql, parameters, warnings。"""


def _strict_json_object(
    text: str, stage: str, error_type: type[InvalidProviderOutputError]
) -> dict:
    if not text or "```" in text:
        raise error_type(f"{stage}输出不是严格 JSON。")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise error_type(f"{stage}输出无法解析。") from exc
    if not isinstance(payload, dict):
        raise error_type(f"{stage}输出必须是 JSON 对象。")
    return payload


def _metric_ids(metric_context: str) -> set[str]:
    try:
        payload = yaml.safe_load(metric_context) or {}
        metrics = payload.get("metrics", [])
        return {item["id"] for item in metrics if isinstance(item, dict) and "id" in item}
    except (yaml.YAMLError, AttributeError, TypeError) as exc:
        raise InvalidSemanticOutputError("指标上下文无法解析。") from exc


def _parse_semantic(payload: dict, allowed_metrics: set[str]) -> BusinessSemantic:
    if not REQUIRED_SEMANTIC_FIELDS.issubset(payload):
        raise InvalidSemanticOutputError("业务语义缺少必要字段。")
    metrics = payload["metrics"]
    dimensions = payload["dimensions"]
    filters = payload["filters"]
    sort = payload["sort"]
    if not all(
        (
            isinstance(payload["intent"], str),
            isinstance(payload["business_domain"], str),
            isinstance(metrics, list) and all(isinstance(item, str) for item in metrics),
            isinstance(dimensions, list) and all(isinstance(item, str) for item in dimensions),
            isinstance(filters, dict) and all(isinstance(key, str) and _is_scalar(value) for key, value in filters.items()),
            payload["time_range"] is None or isinstance(payload["time_range"], dict),
            isinstance(sort, list) and all(isinstance(item, dict) for item in sort),
            payload["limit"] is None or isinstance(payload["limit"], int),
            isinstance(payload["clarification_required"], bool),
            payload["clarification_question"] is None or isinstance(payload["clarification_question"], str),
        )
    ):
        raise InvalidSemanticOutputError("业务语义字段类型不正确。")
    unknown_metrics = set(metrics) - allowed_metrics
    if unknown_metrics:
        raise UnsupportedMetricError("业务语义包含未定义指标。")
    confidence = payload.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise InvalidSemanticOutputError("业务语义置信度必须位于0到1之间。")
    return BusinessSemantic(
        intent=payload["intent"],
        business_domain=payload["business_domain"],
        metrics=metrics,
        dimensions=dimensions,
        filters=filters,
        time_range=payload["time_range"],
        sort=sort,
        limit=payload["limit"],
        clarification_required=payload["clarification_required"],
        clarification_question=payload["clarification_question"],
        confidence=float(confidence) if confidence is not None else None,
    )


def _parse_generated_sql(payload: dict) -> GeneratedSQL:
    sql = payload.get("sql")
    parameters = payload.get("parameters", {})
    warnings = payload.get("warnings", [])
    if not isinstance(sql, str) or not sql.strip():
        raise InvalidSQLOutputError("SQL 输出为空或类型不正确。")
    if "```" in sql:
        raise InvalidSQLOutputError("SQL 不得包含 Markdown 代码围栏。")
    if not isinstance(parameters, dict) or not all(
        isinstance(key, str) and _is_scalar(value)
        for key, value in parameters.items()
    ):
        raise InvalidSQLOutputError("SQL 参数必须是 JSON 标量对象。")
    if not isinstance(warnings, list) or not all(
        isinstance(item, str) for item in warnings
    ):
        raise InvalidSQLOutputError("SQL warnings 格式不正确。")
    return GeneratedSQL(
        sql=sql.strip(),
        parameters=parameters,
        generator_name="llm",
        warnings=warnings,
    )


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
