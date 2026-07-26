from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from calendar import monthrange
from datetime import date
from pathlib import Path

from app.application.errors import ApplicationError, ConfigurationError
from app.application.models import IntentResolution


DIRECT_PATTERNS = (
    re.compile(r"^查询.+?在\d{4}-\d{2}-\d{2}的.+$"),
    re.compile(r"^查询\d{4}-\d{2}-\d{2}.+?机构排名$"),
    re.compile(r"^查询.+?从\d{4}-\d{2}-\d{2}到\d{4}-\d{2}-\d{2}的.+?趋势$"),
)

ANALYSIS_OPTIONS = (
    {"id": "growth_ranking", "label": "机构增长排名"},
    {"id": "institution_ranking", "label": "机构数值排名"},
    {"id": "metric_trend", "label": "机构指标趋势"},
    {"id": "single_value", "label": "机构指标单值"},
)
GROWTH_METHODS = (
    {"id": "year_start", "label": "较年初增长（以上年末为基期）"},
    {"id": "year_over_year", "label": "同比增长"},
    {"id": "month_over_month", "label": "环比增长"},
    {"id": "custom_range", "label": "自定义时间增长"},
)


class InvalidConfirmationError(ApplicationError):
    code = "INVALID_CONFIRMATION"


class RealIntentConfirmationResolver:
    """Resolve incomplete real-data questions before SQL generation.

    Every selectable ID comes from the read-only real catalog or the audited
    analysis directory above. A signed token binds the original question to
    the exact candidate set, and every submitted selection is revalidated.
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.metrics, self.institutions, self.date_min, self.date_max = self._load()
        catalog_fingerprint = json.dumps(
            [self.metrics, self.institutions, self.date_min, self.date_max],
            ensure_ascii=False,
            sort_keys=True,
        )
        self._signing_key = hashlib.sha256(
            ("ycsx-intent-confirmation-v1|" + catalog_fingerprint).encode("utf-8")
        ).digest()

    def resolve(self, question: str, confirmation: dict | None) -> IntentResolution:
        compact = "".join(question.strip().split()).rstrip("。？?")
        if any(pattern.fullmatch(compact) for pattern in DIRECT_PATTERNS):
            if confirmation:
                raise InvalidConfirmationError("明确问题不接受额外确认参数。")
            return IntentResolution(status="direct")

        plan = self._build_plan(question, compact)
        plan["token"] = self._token(plan)
        if confirmation is None:
            return IntentResolution(status="required", confirmation=plan)
        return self._confirm(plan, confirmation)

    def _build_plan(self, question: str, compact: str) -> dict:
        metric_matches = [item for item in self.metrics if item["label"] in compact]
        if not metric_matches:
            aliases = (("存款", "ZB001"), ("贷款", "ZB002"))
            for alias, identifier in aliases:
                if alias in compact:
                    metric_matches = [item for item in self.metrics if item["id"] == identifier]
                    break
        if len(metric_matches) == 1:
            metric_field = self._field("metric", "指标", "recognized", metric_matches[0], [])
        elif len(metric_matches) > 1:
            metric_field = self._field("metric", "指标", "needs_confirmation", None, metric_matches)
        else:
            metric_field = self._field("metric", "指标", "unrecognized", None, self.metrics)

        growth = "增长" in compact or "增量" in compact or "增幅" in compact
        ranking = any(word in compact for word in ("最好", "最高", "最多", "哪家", "排名"))
        if growth and ranking:
            analysis_value = ANALYSIS_OPTIONS[0]
            analysis_field = self._field("analysis", "分析方式", "recognized", analysis_value, [])
            method_field = self._field("growth_method", "增长方式", "needs_confirmation", None, list(GROWTH_METHODS))
        elif ranking:
            analysis_field = self._field("analysis", "分析方式", "recognized", ANALYSIS_OPTIONS[1], [])
            method_field = self._field("growth_method", "增长方式", "unrecognized", None, list(GROWTH_METHODS))
        else:
            analysis_field = self._field("analysis", "分析方式", "unrecognized", None, list(ANALYSIS_OPTIONS))
            method_field = self._field("growth_method", "增长方式", "unrecognized", None, list(GROWTH_METHODS))

        scope = {"id": "all_institutions", "label": f"全部{len(self.institutions)}家正式机构"}
        custom_start = self._field("custom_start_date", "自定义基期", "missing", None, [], required=False)
        custom_start.update({"input_type": "date", "visible_when": {"field": "growth_method", "equals": "custom_range"}})
        custom_end = self._field("custom_end_date", "自定义本期", "missing", None, [], required=False)
        custom_end.update({"input_type": "date", "visible_when": {"field": "growth_method", "equals": "custom_range"}})
        fields = [metric_field, analysis_field, method_field, custom_start, custom_end, self._field("institution_scope", "机构范围", "recognized", scope, [])]
        return {
            "version": "intent-confirmation-v1",
            "status": "required",
            "original_question": question,
            "summary": "系统已识别部分分析意图，请确认缺少或存在歧义的条件后再查询。",
            "fields": fields,
        }

    def _confirm(self, plan: dict, submitted: dict) -> IntentResolution:
        token = submitted.get("token")
        selections = submitted.get("selections")
        if not isinstance(token, str) or not hmac.compare_digest(token, plan["token"]):
            raise InvalidConfirmationError("确认信息已失效或与原问题不匹配，请重新确认。")
        if not isinstance(selections, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in selections.items()):
            raise InvalidConfirmationError("确认选项格式不正确。")
        fields = {field["key"]: field for field in plan["fields"]}
        selectable = {key for key, field in fields.items() if field["state"] in {"missing", "needs_confirmation", "unrecognized"}}
        if set(selections) - selectable:
            raise InvalidConfirmationError("确认请求包含未经允许的字段。")
        chosen: dict[str, dict] = {}
        for key, field in fields.items():
            if field.get("value"):
                chosen[key] = field["value"]
                continue
            selected_id = selections.get(key)
            if field.get("input_type") == "date":
                continue
            options = {option["id"]: option for option in field.get("options", [])}
            if field.get("required", True) and selected_id not in options:
                raise InvalidConfirmationError(f"字段“{field['label']}”的选项无效或尚未选择。")
            if selected_id in options:
                chosen[key] = options[selected_id]
        if chosen.get("analysis", {}).get("id") != "growth_ranking":
            raise InvalidConfirmationError("当前候选版仅开放已审计的机构增长排名确认查询。")
        method_id = chosen.get("growth_method", {}).get("id")
        if method_id not in {item["id"] for item in GROWTH_METHODS}:
            raise InvalidConfirmationError("增长方式不在已审计目录中。")
        custom_keys = {"custom_start_date", "custom_end_date"}
        if method_id != "custom_range" and set(selections) & custom_keys:
            raise InvalidConfirmationError("非自定义增长方式不接受自定义日期。")
        if method_id == "custom_range" and not custom_keys.issubset(selections):
            raise InvalidConfirmationError("自定义时间必须同时填写开始日期和结束日期。")
        metric_id = chosen.get("metric", {}).get("id")
        if metric_id not in {item["id"] for item in self.metrics}:
            raise InvalidConfirmationError("指标不在当前正式目录中。")
        period = self._resolve_dates(metric_id, method_id, selections)
        execution_question = f"__confirmed_growth_ranking__:{metric_id}:{period['start_date']}:{period['end_date']}:{method_id}"
        confirmed = {
            **plan,
            "status": "confirmed",
            "summary": "已按用户确认的条件执行真实数据查询。",
            "final_conditions": {
                "metric": chosen["metric"],
                "analysis": chosen["analysis"],
                "growth_method": chosen["growth_method"],
                "comparison_period": period,
                "institution_scope": chosen["institution_scope"],
            },
        }
        return IntentResolution(status="confirmed", confirmation=confirmed, execution_question=execution_question)

    def _resolve_dates(self, metric_id: str, method_id: str, selections: dict[str, str]) -> dict:
        end = date.fromisoformat(self.date_max)
        method = next(item for item in GROWTH_METHODS if item["id"] == method_id)
        if method_id == "year_start":
            start = date(end.year - 1, 12, 31)
        elif method_id == "year_over_year":
            try:
                start = end.replace(year=end.year - 1)
            except ValueError:
                start = end.replace(year=end.year - 1, day=28)
        elif method_id == "month_over_month":
            year, month = (end.year - 1, 12) if end.month == 1 else (end.year, end.month - 1)
            start = date(year, month, min(end.day, monthrange(year, month)[1]))
        else:
            try:
                start = date.fromisoformat(selections.get("custom_start_date", ""))
                end = date.fromisoformat(selections.get("custom_end_date", ""))
            except ValueError as exc:
                raise InvalidConfirmationError("自定义时间必须填写有效的开始日期和结束日期。") from exc
        if start >= end:
            raise InvalidConfirmationError("增长比较的基期必须早于本期。")
        bounds = date.fromisoformat(self.date_min), date.fromisoformat(self.date_max)
        if start < bounds[0] or end > bounds[1]:
            raise InvalidConfirmationError("所选日期超出正式数据可用范围。")
        for selected_date, label in ((start, "基期"), (end, "本期")):
            if not self._date_available(metric_id, selected_date.isoformat()):
                raise InvalidConfirmationError(f"{label}日期在该正式指标目录中没有数据。")
        return {"id": method_id, "label": method["label"], "start_date": start.isoformat(), "end_date": end.isoformat()}

    def _date_available(self, metric_id: str, data_date: str) -> bool:
        try:
            connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True)
            try:
                return connection.execute("SELECT 1 FROM metric_facts WHERE metric_id = ? AND data_date = ? LIMIT 1", (metric_id, data_date)).fetchone() is not None
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ConfigurationError("正式数据库日期目录无法读取。") from exc

    @staticmethod
    def _field(key: str, label: str, state: str, value: dict | None, options: list[dict], required: bool = True) -> dict:
        return {"key": key, "label": label, "state": state, "required": required, "value": value, "options": options}

    def _token(self, plan: dict) -> str:
        payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(self._signing_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _load(self) -> tuple[list[dict], list[dict], str, str]:
        try:
            connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True)
            try:
                metrics = [{"id": row[0], "label": row[1], "unit": row[2]} for row in connection.execute("SELECT metric_id, metric_name, metric_unit FROM metrics ORDER BY metric_id")]
                institutions = [{"id": row[0], "label": row[1]} for row in connection.execute("SELECT institution_id, institution_name FROM institutions ORDER BY institution_id")]
                bounds = connection.execute("SELECT MIN(data_date), MAX(data_date) FROM metric_facts").fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ConfigurationError("正式数据库意图确认目录无法读取。") from exc
        if not metrics or not institutions or not bounds or not all(bounds):
            raise ConfigurationError("正式数据库意图确认目录不完整。")
        return metrics, institutions, str(bounds[0]), str(bounds[1])
