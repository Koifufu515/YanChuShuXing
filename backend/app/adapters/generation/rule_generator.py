from __future__ import annotations

import re

from app.application.errors import (
    ConfigurationError,
    RuleNotMatchedError,
    UnsupportedQuestionError,
)
from app.application.models import GeneratedSQL, QueryContext, QueryMetadata


BALANCE_PATTERN = re.compile(r"^查询客户(?P<customer_id>C\d+)的账户余额$")
TRANSACTION_PATTERN = re.compile(
    r"^查询客户(?P<customer_id>C\d+)在(?P<year>\d{4})年(?P<month>\d{1,2})月的交易汇总$"
)


class RuleSQLGenerator:
    name = "rule-v1"

    def __init__(self, configured_mode: str = "rule") -> None:
        self.configured_mode = configured_mode

    def _metadata(self) -> QueryMetadata:
        return QueryMetadata(
            configured_mode=self.configured_mode,
            executed_generator="rule",
            rule_matched=True,
            route="Rule",
        )

    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        compact = _normalize(question)
        if compact == "查询有效客户数量":
            _require_tables(context, {"customer_info"})
            return GeneratedSQL(
                sql="""
                    SELECT COUNT(DISTINCT customer_id) AS customer_count
                    FROM customer_info
                    WHERE customer_status = :status
                """.strip(),
                parameters={"status": "ACTIVE"},
                generator_name=self.name,
                metadata=self._metadata(),
            )

        balance_match = BALANCE_PATTERN.fullmatch(compact)
        if balance_match:
            _require_tables(context, {"customer_info", "account_info"})
            return GeneratedSQL(
                sql="""
                    SELECT c.customer_id,
                           SUM(a.current_balance) AS account_balance
                    FROM customer_info AS c
                    JOIN account_info AS a ON a.customer_id = c.customer_id
                    WHERE c.customer_id = :customer_id
                      AND a.account_status = :account_status
                    GROUP BY c.customer_id
                """.strip(),
                parameters={
                    "customer_id": balance_match.group("customer_id"),
                    "account_status": "ACTIVE",
                },
                generator_name=self.name,
                metadata=self._metadata(),
            )

        transaction_match = TRANSACTION_PATTERN.fullmatch(compact)
        if transaction_match:
            _require_tables(context, {"transaction_detail"})
            year = int(transaction_match.group("year"))
            month = int(transaction_match.group("month"))
            if not 1 <= month <= 12:
                raise UnsupportedQuestionError("月份必须位于1到12之间。")
            next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
            return GeneratedSQL(
                sql="""
                    SELECT customer_id,
                           COUNT(CASE WHEN transaction_status = 'SUCCESS' THEN 1 END) AS transaction_count,
                           SUM(CASE WHEN transaction_status = 'SUCCESS' AND direction = 'IN' THEN amount ELSE 0 END) AS total_in,
                           SUM(CASE WHEN transaction_status = 'SUCCESS' AND direction = 'OUT' THEN amount ELSE 0 END) AS total_out,
                           SUM(CASE WHEN transaction_status = 'SUCCESS' AND direction = 'IN' THEN amount
                                    WHEN transaction_status = 'SUCCESS' AND direction = 'OUT' THEN -amount
                                    ELSE 0 END) AS net_amount
                    FROM transaction_detail
                    WHERE customer_id = :customer_id
                      AND transaction_time >= :start_time
                      AND transaction_time < :end_time
                    GROUP BY customer_id
                """.strip(),
                parameters={
                    "customer_id": transaction_match.group("customer_id"),
                    "start_time": f"{year:04d}-{month:02d}-01 00:00:00",
                    "end_time": f"{next_year:04d}-{next_month:02d}-01 00:00:00",
                },
                generator_name=self.name,
                metadata=self._metadata(),
            )

        raise RuleNotMatchedError("首版暂不支持该问题，请尝试预置问题。")


def _normalize(question: str) -> str:
    return "".join(question.strip().split()).rstrip("。？?")


def _require_tables(context: QueryContext, required: set[str]) -> None:
    if not required.issubset(context.allowed_tables):
        missing = ", ".join(sorted(required - context.allowed_tables))
        raise ConfigurationError(f"查询上下文缺少必要表：{missing}")
