from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

from app.application.business_concept_fast_matcher import (
    match_main_metrics_query,
)
from app.application.business_concept_fast_plan import (
    build_main_metrics_plan,
)
from app.application.models import (
    QueryPlanResult,
    QueryPlanValidation,
)
from app.application.query_plan_normalization import (
    normalize_query_plan,
)
from app.application.query_plan_validation import (
    validate_business_rules,
)
from app.ports.query_planner import QueryPlanner


class BusinessConceptFastPlanner:
    """为已冻结业务概念生成确定性查询计划。"""

    def __init__(
        self,
        schema: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        self.schema = schema
        self.context = context
        self.validator = Draft202012Validator(schema)

    def try_plan(
        self,
        question: str,
    ) -> QueryPlanResult | None:
        match = match_main_metrics_query(
            question,
            self.context,
        )

        if match is None:
            return None

        plan = build_main_metrics_plan(
            match,
            self.context,
        )
        validation = self._validate(
            plan,
            question,
        )

        return QueryPlanResult(
            success=validation.success,
            question=question,
            model="deterministic-business-concept",
            latency_ms=0.0,
            repair_attempted=False,
            initial_validation=validation,
            schema_valid=validation.schema_valid,
            schema_errors=validation.schema_errors,
            business_valid=validation.business_valid,
            business_errors=validation.business_errors,
            query_plan=validation.query_plan,
        )

    def _validate(
        self,
        plan: dict[str, Any],
        question: str,
    ) -> QueryPlanValidation:
        normalized_plan = normalize_query_plan(plan)

        schema_errors = sorted(
            self.validator.iter_errors(normalized_plan),
            key=lambda item: list(item.path),
        )

        schema_error_payload = [
            {
                "path": (
                    ".".join(
                        str(part)
                        for part in error.path
                    )
                    or "$"
                ),
                "message": error.message,
            }
            for error in schema_errors
        ]

        business_errors = validate_business_rules(
            normalized_plan,
            self.context,
            question,
        )

        return QueryPlanValidation(
            schema_valid=not schema_errors,
            schema_errors=schema_error_payload,
            business_valid=not business_errors,
            business_errors=business_errors,
            query_plan=normalized_plan,
        )


class RoutingQueryPlanner:
    """快速规划命中则直接返回，否则调用原规划器。"""

    def __init__(
        self,
        fast_planner: BusinessConceptFastPlanner,
        fallback_planner: QueryPlanner,
    ) -> None:
        self.fast_planner = fast_planner
        self.fallback_planner = fallback_planner

    def plan(self, question: str) -> QueryPlanResult:
        fast_result = self.fast_planner.try_plan(
            question
        )

        if fast_result is not None:
            return fast_result

        return self.fallback_planner.plan(question)
