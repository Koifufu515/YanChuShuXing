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


PLAN = {
    "status": {
        "code": "executable",
    },
    "operations": [
        {
            "operator_id": "OP001",
            "params": {
                "institution_id": "ORG009",
            },
        }
    ],
}


class FakePlanner:
    def plan(
        self,
        question: str,
    ) -> QueryPlanResult:
        validation = QueryPlanValidation(
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=PLAN,
        )

        return QueryPlanResult(
            success=True,
            question=question,
            model="test",
            latency_ms=1.0,
            repair_attempted=False,
            initial_validation=validation,
            schema_valid=True,
            schema_errors=[],
            business_valid=True,
            business_errors=[],
            query_plan=PLAN,
        )


class FakeExecutor:
    def __init__(
        self,
        result: QueryPlanExecutionResult,
    ) -> None:
        self.result = result

    def execute(
        self,
        query_plan: dict,
    ) -> QueryPlanExecutionResult:
        return self.result


def principal(
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


def run_pipeline(
    result: QueryPlanExecutionResult,
):
    pipeline = PlannedQueryPipeline(
        query_planner=FakePlanner(),
        query_plan_executor=(
            FakeExecutor(result)
        ),
        audit_logger=NoOpAuditLogger(),
        provider_name="test",
    )

    return pipeline.run(
        QueryCommand(
            question="测试查询",
            user_id="user_org009",
            conversation_id="security_test",
            request_id="req_security_test",
            security_principal=principal(),
        )
    )


class PlannedPipelineResultSecurityTest(
    unittest.TestCase
):
    def test_masks_and_removes_fields_before_response(
        self,
    ) -> None:
        outcome = run_pipeline(
            QueryPlanExecutionResult(
                columns=[
                    "机构名称",
                    "客户姓名",
                    "手机号",
                    "api_key",
                ],
                rows=[
                    [
                        "江苏省I市农商行",
                        "张三",
                        "13812345678",
                        "raw-secret",
                    ]
                ],
                summary=(
                    "原始摘要含有张三和手机号。"
                ),
            )
        )

        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.columns,
            [
                "机构名称",
                "客户姓名",
                "手机号",
            ],
        )
        self.assertEqual(
            outcome.rows,
            [
                [
                    "江苏省I市农商行",
                    "张*",
                    "138****5678",
                ]
            ],
        )
        self.assertNotIn(
            "张三",
            outcome.summary or "",
        )
        self.assertIsNone(outcome.answer)
        self.assertEqual(
            len(outcome.warnings),
            2,
        )

    def test_business_metrics_remain_unchanged(
        self,
    ) -> None:
        outcome = run_pipeline(
            QueryPlanExecutionResult(
                columns=[
                    "机构编号",
                    "机构名称",
                    "指标名称",
                    "指标值",
                ],
                rows=[
                    [
                        "ORG009",
                        "江苏省I市农商行",
                        "不良贷款率",
                        1.46,
                    ]
                ],
                summary="查询成功。",
            )
        )

        self.assertIsNone(outcome.error)
        self.assertEqual(
            outcome.rows[0][-1],
            1.46,
        )
        self.assertEqual(
            outcome.summary,
            "查询成功。",
        )
        self.assertEqual(
            outcome.warnings,
            [],
        )


if __name__ == "__main__":
    unittest.main()
