from __future__ import annotations

from pathlib import Path

import yaml

from app.application.errors import ConfigurationError
from app.application.models import QueryContext


class YAMLContextResolver:
    def __init__(self, schema_path: Path, metrics_path: Path) -> None:
        self.schema_path = Path(schema_path)
        self.metrics_path = Path(metrics_path)
        try:
            self.schema = yaml.safe_load(self.schema_path.read_text(encoding="utf-8"))
            self.metrics = yaml.safe_load(self.metrics_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigurationError("Schema 或指标配置无法加载。") from exc

    def resolve(self, question: str) -> QueryContext:
        table_names, metric_ids = self._select_context(question)
        tables = self.schema.get("tables", {})
        selected_tables = {
            name: tables[name] for name in table_names if name in tables
        }
        relationships = [
            relationship
            for relationship in self.schema.get("relationships", [])
            if _relationship_tables(relationship).issubset(table_names)
        ]
        selected_metrics = [
            metric
            for metric in self.metrics.get("metrics", [])
            if metric.get("id") in metric_ids
        ]
        return QueryContext(
            schema_context=yaml.safe_dump(
                {"tables": selected_tables, "relationships": relationships},
                allow_unicode=True,
                sort_keys=False,
            ),
            metric_context=yaml.safe_dump(
                {"metrics": selected_metrics}, allow_unicode=True, sort_keys=False
            ),
            allowed_tables=frozenset(table_names),
            denied_columns=frozenset({"manager_name"}),
        )

    def _select_context(self, question: str) -> tuple[set[str], set[str]]:
        compact = "".join(question.split())
        if "账户余额" in compact:
            return {"customer_info", "account_info"}, {"deposit_balance"}
        if "交易汇总" in compact:
            return {"transaction_detail"}, {
                "transaction_count",
                "transaction_inflow",
                "transaction_outflow",
                "net_transaction_flow",
            }
        if "客户数量" in compact or "客户数" in compact:
            return {"customer_info"}, {"active_customer_count"}
        return set(self.schema.get("tables", {})), set()


def _relationship_tables(relationship: dict[str, str]) -> set[str]:
    return {
        relationship["from"].split(".", 1)[0],
        relationship["to"].split(".", 1)[0],
    }
