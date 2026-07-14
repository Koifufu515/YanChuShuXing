from app.application.models import SafetyResult, UserContext
from app.core.sql_safety import SqlSafetyPolicy, SqlSafetyValidator


class SQLGlotSafetyChecker:
    def validate(self, sql: str, user_context: UserContext) -> SafetyResult:
        validator = SqlSafetyValidator(
            SqlSafetyPolicy(
                allowed_tables=user_context.allowed_tables,
                denied_columns=user_context.denied_columns,
            )
        )
        report = validator.validate(sql)
        warnings = [
            finding.message
            for finding in report.findings
            if finding.severity in {"warning", "info"}
        ]
        error_messages = [
            finding.message
            for finding in report.findings
            if finding.severity == "error"
        ]
        return SafetyResult(
            allowed=report.allowed,
            warnings=warnings,
            error_code=None if report.allowed else "SQL_REJECTED",
            error_message=None if report.allowed else "；".join(error_messages),
            referenced_tables=report.referenced_tables,
        )
