from app.application.errors import RuleNotMatchedError
from app.application.models import GeneratedSQL, QueryContext


class RealRuleSQLGenerator:
    """Real mode has no approved deterministic rules in this integration sprint."""

    name = "real-rule"

    def generate(self, question: str, context: QueryContext) -> GeneratedSQL:
        raise RuleNotMatchedError("该正式数据问题尚未配置确定性规则。")
