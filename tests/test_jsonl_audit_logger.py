from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from app.adapters.audit.jsonl_logger import (
    JsonlAuditLogger,
)
from app.application.models import AuditEvent


class JsonlAuditLoggerTest(
    unittest.TestCase
):
    def test_records_audit_without_raw_sensitive_text(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = (
                Path(root)
                / "audit"
                / "query_audit.jsonl"
            )
            logger = JsonlAuditLogger(path)

            question = (
                "江苏省I市农商行"
                "2025年不良贷款率是多少？"
            )
            sql = (
                "SELECT metric_value "
                "FROM metric_facts"
            )

            logger.record(
                AuditEvent(
                    event_type=(
                        "request_started"
                    ),
                    request_id="req_test_001",
                    user_id="demo_user",
                    question=question,
                )
            )
            logger.record(
                AuditEvent(
                    event_type=(
                        "query_succeeded"
                    ),
                    request_id="req_test_001",
                    user_id="demo_user",
                    question=question,
                    sql=sql,
                )
            )

            raw_text = path.read_text(
                encoding="utf-8"
            )
            records = [
                json.loads(line)
                for line
                in raw_text.splitlines()
                if line.strip()
            ]

            self.assertEqual(
                len(records),
                2,
            )
            self.assertEqual(
                records[0]["event_type"],
                "request_started",
            )
            self.assertEqual(
                records[1]["event_type"],
                "query_succeeded",
            )
            self.assertEqual(
                records[0]["request_id"],
                "req_test_001",
            )
            self.assertEqual(
                records[0][
                    "question_characters"
                ],
                len(question),
            )
            self.assertFalse(
                records[0]["sql_present"]
            )
            self.assertTrue(
                records[1]["sql_present"]
            )

            self.assertEqual(
                records[0][
                    "actor_sha256"
                ],
                records[1][
                    "actor_sha256"
                ],
            )
            self.assertEqual(
                records[0][
                    "question_sha256"
                ],
                records[1][
                    "question_sha256"
                ],
            )

            self.assertNotIn(
                question,
                raw_text,
            )
            self.assertNotIn(
                sql,
                raw_text,
            )
            self.assertNotIn(
                "demo_user",
                raw_text,
            )

            permissions = stat.S_IMODE(
                path.stat().st_mode
            )
            self.assertEqual(
                permissions,
                0o600,
            )


if __name__ == "__main__":
    unittest.main()
