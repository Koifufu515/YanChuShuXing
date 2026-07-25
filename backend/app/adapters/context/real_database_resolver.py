from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from app.application.errors import ConfigurationError
from app.application.models import QueryContext


REAL_TABLES = frozenset({"institutions", "metrics", "metric_facts"})


class RealDatabaseContextResolver:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.is_file():
            raise ConfigurationError("正式数据库尚未初始化，请先执行正式数据导入和验收。")
        self._metrics, self._institutions = self._load_catalogs()

    def resolve(self, question: str) -> QueryContext:
        schema = {
            "dialect": "SQLite",
            "tables": {
                "institutions": {
                    "columns": {"institution_id": "机构编号", "institution_name": "机构名称"}
                },
                "metrics": {
                    "columns": {
                        "metric_id": "指标编号",
                        "metric_name": "指标名称",
                        "metric_definition": "指标说明",
                        "metric_unit": "指标单位",
                        "value_scale": "定点数缩放位数",
                    }
                },
                "metric_facts": {
                    "columns": {
                        "data_date": "数据日期，YYYY-MM-DD",
                        "metric_id": "指标编号，关联 metrics",
                        "institution_id": "机构编号，关联 institutions",
                        "metric_value_scaled": "定点整数值，查询业务值必须调用 scaled_value(metric_value_scaled, value_scale)",
                    }
                },
            },
            "relationships": [
                "metric_facts.institution_id = institutions.institution_id",
                "metric_facts.metric_id = metrics.metric_id",
            ],
            "constraints": [
                "只允许 institutions、metrics、metric_facts 三张表",
                "业务值统一使用 scaled_value(metric_value_scaled, value_scale)",
                "当前正式发布包含13家机构，机构名称必须从机构上下文选择",
            ],
        }
        metrics = {
            "metrics": [
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "unit": row[3],
                    "value_scale": row[4],
                }
                for row in self._metrics
            ]
        }
        institutions = {
            "institutions": [
                {"id": row[0], "name": row[1]} for row in self._institutions
            ]
        }
        return QueryContext(
            schema_context=yaml.safe_dump(schema, allow_unicode=True, sort_keys=False),
            metric_context=yaml.safe_dump(metrics, allow_unicode=True, sort_keys=False),
            institution_context=yaml.safe_dump(
                institutions, allow_unicode=True, sort_keys=False
            ),
            allowed_tables=REAL_TABLES,
        )

    def _load_catalogs(self) -> tuple[list[tuple], list[tuple]]:
        try:
            connection = sqlite3.connect(
                f"file:{self.database_path}?mode=ro", uri=True
            )
            try:
                metrics = connection.execute(
                    "SELECT metric_id, metric_name, metric_definition, metric_unit, value_scale "
                    "FROM metrics ORDER BY metric_id"
                ).fetchall()
                institutions = connection.execute(
                    "SELECT institution_id, institution_name FROM institutions ORDER BY institution_id"
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ConfigurationError("正式数据库业务目录无法读取。") from exc
        return metrics, institutions
