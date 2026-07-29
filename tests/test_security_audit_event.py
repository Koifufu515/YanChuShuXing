from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.adapters.audit.jsonl_logger import (
    JsonlAuditLogger,
)
from app.application.models import (
    AuditEvent,
)


class SecurityAuditEventTest(
    unittest.TestCase
):
    def test_records_access_denial_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "audit.jsonl"
            logger = JsonlAuditLogger(path)

            logger.record(
                AuditEvent(
                    event_type="access_denied",
                    request_id="req_denied_001",
                    user_id="sensitive_user_id",
                    question="查询其他机构经营指标",
                    error_code="ACCESS_DENIED",
                    actor_role=(
                        "institution_analyst"
                    ),
                    authenticated=True,
                    security_action=(
                        "institution_scope_denied"
                    ),
                    masking_profile="standard",
                    referenced_institution_count=1,
                )
            )

            raw_text = path.read_text(
                encoding="utf-8"
            )
            record = json.loads(raw_text)

            self.assertEqual(
                record["event_version"],
                2,
            )
            self.assertEqual(
                record["event_type"],
                "access_denied",
            )
            self.assertEqual(
                record["error_code"],
                "ACCESS_DENIED",
            )
            self.assertEqual(
                record["actor_role"],
                "institution_analyst",
            )
            self.assertTrue(
                record["authenticated"]
            )
            self.assertEqual(
                record["security_action"],
                "institution_scope_denied",
            )
            self.assertEqual(
                record[
                    "referenced_institution_count"
                ],
                1,
            )

            self.assertNotIn(
                "sensitive_user_id",
                raw_text,
            )
            self.assertNotIn(
                "查询其他机构经营指标",
                raw_text,
            )

    def test_records_dynamic_masking_metadata(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "audit.jsonl"
            logger = JsonlAuditLogger(path)

            logger.record(
                AuditEvent(
                    event_type="result_secured",
                    request_id="req_masked_001",
                    user_id="audit_user",
                    question="查询客户数据",
                    actor_role="auditor",
                    authenticated=True,
                    security_action=(
                        "dynamic_masking"
                    ),
                    masking_profile="strict",
                    affected_column_count=3,
                    referenced_institution_count=1,
                )
            )

            record = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                record["security_action"],
                "dynamic_masking",
            )
            self.assertEqual(
                record["masking_profile"],
                "strict",
            )
            self.assertEqual(
                record["affected_column_count"],
                3,
            )
            self.assertIsNone(
                record["error_code"]
            )


if __name__ == "__main__":
    unittest.main()
