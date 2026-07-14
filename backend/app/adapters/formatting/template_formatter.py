from __future__ import annotations

from app.application.models import FormattedResult, QueryResult


class TemplateResultFormatter:
    def format(self, question: str, result: QueryResult) -> FormattedResult:
        warnings = (
            ["结果超过最大返回行数，已截断。"] if result.truncated else []
        )
        if not result.rows:
            return FormattedResult(
                summary="未查询到符合条件的数据。", warnings=warnings
            )

        values = dict(zip(result.columns, result.rows[0]))
        if "customer_count" in values:
            summary = f"当前有效客户数量为{int(values['customer_count'])}户。"
        elif {"customer_id", "account_balance"}.issubset(values):
            summary = (
                f"客户{values['customer_id']}当前有效账户余额合计为"
                f"{_ten_thousand(values['account_balance']):.2f}万元。"
            )
        elif {
            "customer_id",
            "transaction_count",
            "total_in",
            "total_out",
            "net_amount",
        }.issubset(values):
            net_amount = float(values["net_amount"] or 0)
            net_label = "净流入" if net_amount >= 0 else "净流出"
            summary = (
                f"客户{values['customer_id']}在该期间共有"
                f"{int(values['transaction_count'])}笔成功交易，"
                f"流入{_ten_thousand(values['total_in']):.2f}万元，"
                f"流出{_ten_thousand(values['total_out']):.2f}万元，"
                f"{net_label}{abs(net_amount) / 10_000:.2f}万元。"
            )
        else:
            summary = f"查询返回{result.row_count}条记录。"

        return FormattedResult(summary=summary, warnings=warnings)


def _ten_thousand(value: object) -> float:
    return float(value or 0) / 10_000
