from __future__ import annotations

from app.application.models import FormattedResult, QueryResult


class RealResultFormatter:
    def format(self, question: str, result: QueryResult) -> FormattedResult:
        warnings = ["结果超过最大返回行数，已截断。"] if result.truncated else []
        if not result.rows:
            return FormattedResult("未查询到符合条件的正式经营数据。", warnings=warnings)
        first = dict(zip(result.columns, result.rows[0]))
        if result.row_count == 1 and "metric_value" in first:
            institution = first.get("institution_name") or first.get("institution_id") or "该机构"
            metric = first.get("metric_name") or first.get("metric_id") or "该指标"
            date = first.get("data_date")
            unit = first.get("metric_unit") or ""
            value = _display_number(first["metric_value"])
            when = f"在{date}" if date else "当前"
            summary = f"{institution}{when}的{metric}为{value}{unit}。"
        else:
            details = []
            for key, label in (("institution_name", "机构"), ("metric_name", "指标"), ("data_date", "日期")):
                if key in result.columns:
                    values = {row[result.columns.index(key)] for row in result.rows}
                    if len(values) == 1:
                        details.append(f"{label}{next(iter(values))}")
            suffix = f"，涉及{'、'.join(details)}" if details else ""
            summary = f"共查询到{result.row_count}条正式经营数据{suffix}。"
        return FormattedResult(summary=summary, warnings=warnings)


def _display_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}"
