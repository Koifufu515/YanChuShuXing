from __future__ import annotations

import unittest

from app.application.models import (
    AuditEvent,
    QueryCommand,
    QueryPlanExecutionResult,
)
from app.application.planned_pipeline import (
    PlannedQueryPipeline,
)
from app.application.security_models import (
    SecurityPrincipal,
)
from tests.test_planned_pipeline_result_security import (
    FakeExecutor,
    FakePlanner,
    principal,
)


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(
        self,
        event: AuditEvent,
    ) -> None:
        self.events.append(event)


class FailingExecutor:
    def execute(
        self,
        query_plan: dict,
    ) -> QueryPlanExecutionResult:
        raise AssertionError(
            "越权查询不应调用执行器。"
        )


def command(
    security_principal: SecurityPrincipal,
) -> QueryCommand:
    return QueryCommand(
        question="测试安全审计",
        user_id=security_principal.subject_id,
        conversation_id="audit_test",
        request_id="req_audit_test",
        security_principal=security_principal,
    )


class PlannedPipelineSecurityAuditTest(
    unittest.TestCase
):
    def test_records_institution_access_denial(
        self,
    ) -> None:
        logger = CapturingAuditLogger()

        denied_principal = SecurityPrincipal(
            subject_id="user_org013",
            display_name="M市机构分析岗",
            role="institution_analyst",
            allowed_institution_ids=(
                frozenset({"ORG013"})
            ),
            masking_profile="standard",
            authenticated=True,
        )

        pipeline = PlannedQueryPipeline(
            query_planner=FakePlanner(),
            query_plan_executor=FailingExecutor(),
            audit_logger=logger,
            provider_name="test",
        )

        outcome = pipeline.run(
            command(denied_principal)
        )

        self.assertIsNotNone(outcome.error)
        self.assertEqual(
            outcome.error.code,
            "ACCESS_DENIED",
        )

        denied_events = [
            event
            for event in logger.events
            if event.security_action
            == "institution_scope_denied"
        ]

        self.assertEqual(
            len(denied_events),
            1,
        )

        event = denied_events[0]

        self.assertEqual(
            event.event_type,
            "access_denied",
        )
        self.assertEqual(
            event.actor_role,
            "institution_analyst",
        )
        self.assertTrue(
            event.authenticated
        )
        self.assertEqual(
            event.referenced_institution_count,
            1,
        )

    def test_records_field_filter_and_masking(
        self,
    ) -> None:
        logger = CapturingAuditLogger()

        execution = QueryPlanExecutionResult(
            columns=[
                "机构名称",
                "客户姓名",
                "api_key",
            ],
            rows=[
                [
                    "江苏省I市农商行",
                    "张三",
                    "raw-secret",
                ]
            ],
            summary="原始查询摘要。",
        )

        pipeline = PlannedQueryPipeline(
            query_planner=FakePlanner(),
            query_plan_executor=(
                FakeExecutor(execution)
            ),
            audit_logger=logger,
            provider_name="test",
        )

        outcome = pipeline.run(
            command(principal())
        )

        self.assertIsNone(outcome.error)

        secured_events = {
            event.security_action: event
            for event in logger.events
            if event.event_type
            == "result_secured"
        }

        self.assertEqual(
            set(secured_events),
            {
                "field_access_filtered",
                "dynamic_masking",
            },
        )

        self.assertEqual(
            secured_events[
                "field_access_filtered"
            ].affected_column_count,
            1,
        )
        self.assertEqual(
            secured_events[
                "dynamic_masking"
            ].affected_column_count,
            1,
        )
        self.assertEqual(
            secured_events[
                "dynamic_masking"
            ].masking_profile,
            "standard",
        )


if __name__ == "__main__":
    unittest.main()
