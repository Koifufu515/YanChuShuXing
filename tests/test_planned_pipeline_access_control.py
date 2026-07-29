from __future__ import annotations

import unittest

from app.adapters.audit.noop_logger import (
    NoOpAuditLogger,
)
from app.application.models import (
    QueryCommand,
    QueryPlanExecutionResult,
    QueryPlanResult,
    QueryPlanValidation,
)
from app.application.planned_pipeline import (
    PlannedQueryPipeline,
)
from app.application.security_models import (
    SecurityPrincipal,
)


def query_plan(
    institution_id: str,
) -> dict:
    return {
        "status": {
            "code": "executable",
        },
        "operations": [
            {
                "operation_id": "step_1",
                "operator_id": "OP001",
                "params": {
                    "institution_id": institution_id,
                    "metric_id": "ZB013",
                    "date": "2025-11-30",
                },
            }
        ],
    }


class FakePlanner:
    def __init__(self, plan: dict) -> None:
        self.query_plan = plan

    def plan(self, question: str) -> QueryPlanResult:
        validation = QueryPlanValidation(
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=self.query_plan,
        )

        return QueryPlanResult(
            success=True,
            question=question,
            model="test-planner",
            latency_ms=1.0,
            repair_attempted=False,
            initial_validation=validation,
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=self.query_plan,
        )


class CapturingExecutor:
    def __init__(self) -> None:
        self.call_count = 0

    def execute(
        self,
        plan: dict,
    ) -> QueryPlanExecutionResult:
        self.call_count += 1

        return QueryPlanExecutionResult(
            columns=["value"],
            rows=[[1.46]],
            summary="查询成功。",
        )


def institution_principal(
) -> SecurityPrincipal:
    return SecurityPrincipal(
        subject_id="user_org009",
        display_name="I市机构分析岗",
        role="institution_analyst",
        allowed_institution_ids=(
            frozenset({"ORG009"})
        ),
        masking_profile="standard",
        authenticated=True,
    )


class PlannedPipelineAccessControlTest(
    unittest.TestCase
):
    def run_pipeline(
        self,
        institution_id: str,
    ):
        executor = CapturingExecutor()

        pipeline = PlannedQueryPipeline(
            query_planner=FakePlanner(
                query_plan(institution_id)
            ),
            query_plan_executor=executor,
            audit_logger=NoOpAuditLogger(),
            provider_name="test",
        )

        outcome = pipeline.run(
            QueryCommand(
                question="查询不良贷款率",
                user_id="user_org009",
                conversation_id="security_test",
                request_id="req_security_test",
                security_principal=(
                    institution_principal()
                ),
            )
        )

        return outcome, executor

    def test_own_institution_reaches_executor(
        self,
    ) -> None:
        outcome, executor = self.run_pipeline(
            "ORG009"
        )

        self.assertIsNone(outcome.error)
        self.assertEqual(
            executor.call_count,
            1,
        )
        self.assertEqual(
            outcome.rows,
            [[1.46]],
        )

    def test_other_institution_is_denied_before_execution(
        self,
    ) -> None:
        outcome, executor = self.run_pipeline(
            "ORG013"
        )

        self.assertIsNotNone(outcome.error)
        self.assertEqual(
            outcome.error.code,
            "ACCESS_DENIED",
        )
        self.assertEqual(
            executor.call_count,
            0,
        )
        self.assertEqual(
            outcome.rows,
            [],
        )


if __name__ == "__main__":
    unittest.main()
