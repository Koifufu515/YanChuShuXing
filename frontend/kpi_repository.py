from __future__ import annotations

from frontend.api_client import BankInsightClient


def load_overview_metrics(client: BankInsightClient) -> list[tuple[str, str]]:
    payload = client.ready().payload
    if payload.get("status") != "ready":
        raise OSError(str(payload.get("error") or "经营概览数据暂时不可用。"))
    if payload.get("data_environment") == "real":
        date_min = payload.get("date_min") or "-"
        date_max = payload.get("date_max") or "-"
        return [
            ("机构数量", _number(payload.get("institution_count"))),
            ("基础指标数量", _number(payload.get("metric_count"))),
            ("数据日期范围", f"{date_min} 至 {date_max}"),
            ("事实记录数量", _number(payload.get("fact_count"))),
        ]
    return [
        ("数据环境", "Demo"),
        ("数据库状态", "已就绪"),
        ("查询链路", "可用"),
        ("数据模式", "演示基线"),
    ]


def _number(value: object) -> str:
    return f"{int(value):,}" if isinstance(value, (int, float)) else "-"
