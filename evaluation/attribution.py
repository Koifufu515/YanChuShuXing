from __future__ import annotations

from dataclasses import dataclass

from evaluation.models import SCORE_CORRECT, SCORE_NEEDS_MANUAL_REVIEW


@dataclass(frozen=True)
class Attribution:
    stage: str
    owner: str


_SEMANTIC = Attribution("语义理解", "05号复核业务口径；技术实现交项目负责人")
_SQL_GENERATION = Attribution("SQL生成", "生成模块开发成员/项目负责人")
_MODEL = Attribution("模型可用性", "项目负责人")
_SAFETY = Attribution("安全层", "安全模块开发成员/项目负责人")
_DATABASE = Attribution("数据库执行", "04号数据负责人")
_VALIDATION = Attribution("接口校验", "06号检查评测输入")
_ENVIRONMENT = Attribution("评测环境", "06号检查后端服务与网络")
_INTERNAL = Attribution("系统内部", "项目负责人")
_UNKNOWN = Attribution("未分类错误", "06号人工归因")

_ERROR_STAGE_MAP: dict[str, Attribution] = {
    "UNSUPPORTED_QUESTION": _SEMANTIC,
    "CLARIFICATION_REQUIRED": _SEMANTIC,
    "INVALID_SEMANTIC_OUTPUT": _SEMANTIC,
    "UNSUPPORTED_METRIC": _SEMANTIC,
    "INVALID_QUESTION": _SEMANTIC,
    "INVALID_SQL_OUTPUT": _SQL_GENERATION,
    "LLM_TIMEOUT": _MODEL,
    "LLM_UNAVAILABLE": _MODEL,
    "LLM_PROVIDER_ERROR": _MODEL,
    "SQL_REJECTED": _SAFETY,
    "ACCESS_DENIED": _SAFETY,
    "QUERY_EXECUTION_ERROR": _DATABASE,
    "QUERY_TIMEOUT": _DATABASE,
    "DATABASE_UNAVAILABLE": _DATABASE,
    "REQUEST_VALIDATION_ERROR": _VALIDATION,
    "API_CONNECTION_ERROR": _ENVIRONMENT,
    "INTERNAL_ERROR": _INTERNAL,
}


def attribute(error_code: str | None, score_status: str) -> Attribution | None:
    if error_code:
        return _ERROR_STAGE_MAP.get(error_code, _UNKNOWN)
    if score_status == SCORE_CORRECT:
        return None
    if score_status == SCORE_NEEDS_MANUAL_REVIEW:
        return Attribution("待人工判分", "06号人工判分后再归因")
    return Attribution("结果不一致", "06号人工复核证据后分派05号/04号/开发成员")
