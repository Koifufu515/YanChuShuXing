from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.models.query import SafetyFinding, SafetyReport


@dataclass(frozen=True)
class SqlSafetyPolicy:
    dialect: str = "sqlite"
    allowed_tables: frozenset[str] = field(default_factory=frozenset)
    denied_columns: frozenset[str] = field(default_factory=frozenset)
    denied_table_prefixes: tuple[str, ...] = (
        "sqlite_",
        "information_schema",
        "pg_",
        "mysql.",
    )


class SqlSafetyValidator:
    """Validate generated SQL structurally before it reaches a database."""

    FORBIDDEN_NODES = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
        exp.Merge,
    )

    def __init__(self, policy: SqlSafetyPolicy) -> None:
        self.policy = policy

    def validate(self, sql: str) -> SafetyReport:
        findings: list[SafetyFinding] = []

        try:
            statements = parse(sql, read=self.policy.dialect)
        except ParseError as exc:
            return SafetyReport(
                allowed=False,
                findings=[
                    SafetyFinding(
                        code="SQL_PARSE_ERROR",
                        severity="error",
                        message=f"SQL 无法解析：{exc}",
                    )
                ],
            )

        if not statements:
            return SafetyReport(
                allowed=False,
                findings=[
                    SafetyFinding(
                        code="EMPTY_SQL",
                        severity="error",
                        message="SQL 不能为空。",
                    )
                ],
            )

        if len(statements) != 1:
            return SafetyReport(
                allowed=False,
                findings=[
                    SafetyFinding(
                        code="MULTI_STATEMENT",
                        severity="error",
                        message="只允许执行一条查询语句。",
                    )
                ],
            )

        statement = statements[0]
        forbidden = next(statement.find_all(*self.FORBIDDEN_NODES), None)
        if forbidden is not None:
            findings.append(
                SafetyFinding(
                    code="FORBIDDEN_OPERATION",
                    severity="error",
                    message=f"检测到禁止操作：{forbidden.key.upper()}。",
                )
            )

        if not isinstance(statement, (exp.Query, exp.Union)):
            findings.append(
                SafetyFinding(
                    code="NOT_READ_ONLY_QUERY",
                    severity="error",
                    message="查询必须是 SELECT、WITH 或 UNION 形式的只读语句。",
                )
            )

        cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
        tables = {
            table.name.lower()
            for table in statement.find_all(exp.Table)
            if table.name and table.name.lower() not in cte_names
        }
        columns = {
            column.name.lower()
            for column in statement.find_all(exp.Column)
            if column.name
        }

        denied_system_tables = sorted(
            table
            for table in tables
            if table.startswith(self.policy.denied_table_prefixes)
        )
        if denied_system_tables:
            findings.append(
                SafetyFinding(
                    code="SYSTEM_TABLE_ACCESS",
                    severity="error",
                    message=f"禁止访问系统表：{', '.join(denied_system_tables)}。",
                )
            )

        unknown_tables = sorted(tables - self.policy.allowed_tables)
        if self.policy.allowed_tables and unknown_tables:
            findings.append(
                SafetyFinding(
                    code="TABLE_NOT_ALLOWED",
                    severity="error",
                    message=f"表不在允许范围内：{', '.join(unknown_tables)}。",
                )
            )

        denied_columns = sorted(columns & self.policy.denied_columns)
        if denied_columns:
            findings.append(
                SafetyFinding(
                    code="SENSITIVE_COLUMN",
                    severity="error",
                    message=f"当前角色无权访问字段：{', '.join(denied_columns)}。",
                )
            )

        allowed = not any(item.severity == "error" for item in findings)
        return SafetyReport(
            allowed=allowed,
            findings=findings,
            referenced_tables=sorted(tables),
            referenced_columns=sorted(columns),
        )
