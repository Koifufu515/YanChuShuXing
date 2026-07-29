from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from app.application.security_alerts import (
    SecurityAlertRecord,
)


_SHA256_PATTERN = re.compile(
    r"^[0-9a-f]{64}$"
)
_VALID_SEVERITIES = {
    "medium",
    "high",
    "critical",
}


class JsonlSecurityAlertReader:
    def __init__(
        self,
        path: Path,
    ) -> None:
        self.path = Path(path)

    def read_recent(
        self,
        limit: int = 50,
    ) -> list[SecurityAlertRecord]:
        if not 1 <= limit <= 200:
            raise ValueError(
                "告警读取数量必须在1到200之间。"
            )

        if not self.path.exists():
            return []

        records: deque[
            SecurityAlertRecord
        ] = deque(maxlen=limit)

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                record = self._parse_line(line)

                if record is not None:
                    records.append(record)

        return list(reversed(records))

    @staticmethod
    def _parse_line(
        line: str,
    ) -> SecurityAlertRecord | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        try:
            occurred_at = datetime.fromisoformat(
                str(payload["occurred_at"])
                .replace("Z", "+00:00")
            )
            event_count = int(
                payload["event_count"]
            )
            window_seconds = int(
                payload["window_seconds"]
            )
            severity = str(
                payload["severity"]
            )
            actor_sha256 = str(
                payload["actor_sha256"]
            )

            if occurred_at.tzinfo is None:
                return None
            if severity not in _VALID_SEVERITIES:
                return None
            if event_count <= 0:
                return None
            if window_seconds <= 0:
                return None
            if not _SHA256_PATTERN.fullmatch(
                actor_sha256
            ):
                return None

            return SecurityAlertRecord(
                occurred_at=occurred_at,
                alert_type=_required_text(
                    payload,
                    "alert_type",
                ),
                severity=severity,
                event_count=event_count,
                window_seconds=window_seconds,
                security_action=_required_text(
                    payload,
                    "security_action",
                ),
                trigger_event_type=_required_text(
                    payload,
                    "trigger_event_type",
                ),
                trigger_error_code=_optional_text(
                    payload.get(
                        "trigger_error_code"
                    )
                ),
                request_id=_required_text(
                    payload,
                    "request_id",
                ),
                actor_sha256=actor_sha256,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return None


def _required_text(
    payload: dict[str, Any],
    key: str,
) -> str:
    value = str(payload[key]).strip()

    if not value:
        raise ValueError(
            f"{key}不能为空。"
        )

    return value


def _optional_text(
    value: object,
) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None
