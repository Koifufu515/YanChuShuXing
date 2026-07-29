from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.adapters.audit.jsonl_alert_reader import (
    JsonlSecurityAlertReader,
)


def payload(
    *,
    request_id: str,
    occurred_at: str,
) -> dict[str, object]:
    return {
        "event_version": 1,
        "occurred_at": occurred_at,
        "alert_type": (
            "repeated_authentication_failure"
        ),
        "severity": "medium",
        "event_count": 5,
        "window_seconds": 300,
        "security_action": (
            "authentication_failure_threshold"
        ),
        "trigger_event_type": (
            "authentication_failed"
        ),
        "trigger_error_code": (
            "INVALID_AUTHENTICATION"
        ),
        "request_id": request_id,
        "actor_sha256": "a" * 64,
    }


class JsonlSecurityAlertReaderTest(
    unittest.TestCase
):
    def test_missing_file_returns_empty(
        self,
    ) -> None:
        reader = JsonlSecurityAlertReader(
            Path("/tmp/missing-alert-file")
        )

        self.assertEqual(
            reader.read_recent(),
            [],
        )

    def test_reads_newest_valid_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "alerts.jsonl"

            lines = [
                json.dumps(
                    payload(
                        request_id="req_1",
                        occurred_at=(
                            "2026-07-29T09:00:00+00:00"
                        ),
                    )
                ),
                "{partial",
                json.dumps(
                    payload(
                        request_id="req_2",
                        occurred_at=(
                            "2026-07-29T09:01:00+00:00"
                        ),
                    )
                ),
            ]

            path.write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )

            records = (
                JsonlSecurityAlertReader(path)
                .read_recent(limit=2)
            )

            self.assertEqual(
                [
                    item.request_id
                    for item in records
                ],
                ["req_2", "req_1"],
            )
            self.assertEqual(
                records[0].actor_sha256,
                "a" * 64,
            )

    def test_rejects_invalid_limit(
        self,
    ) -> None:
        reader = JsonlSecurityAlertReader(
            Path("/tmp/unused-alert-file")
        )

        for limit in (0, 201):
            with self.assertRaises(
                ValueError
            ):
                reader.read_recent(
                    limit=limit
                )


if __name__ == "__main__":
    unittest.main()
