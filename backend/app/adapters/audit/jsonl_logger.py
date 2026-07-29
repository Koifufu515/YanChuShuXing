from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.application.models import AuditEvent


class JsonlAuditLogger:
    """
    将查询审计事件追加写入本地JSONL文件。

    隐私边界：
    1. 不保存原始自然语言问题；
    2. 不保存原始SQL；
    3. 不保存原始用户标识；
    4. 仅保存稳定摘要、长度、事件状态和请求编号。
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def record(self, event: AuditEvent) -> None:
        question = event.question or ""
        sql = event.sql or ""

        payload = {
            "event_version": 2,
            "occurred_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "event_type": event.event_type,
            "request_id": event.request_id,
            "actor_sha256": _sha256(
                event.user_id
            ),
            "question_sha256": _sha256(
                question
            ),
            "question_characters": len(
                question
            ),
            "sql_present": bool(sql),
            "sql_sha256": (
                _sha256(sql)
                if sql
                else None
            ),
            "error_code": event.error_code,
            "actor_role": event.actor_role,
            "authenticated": event.authenticated,
            "security_action": event.security_action,
            "masking_profile": event.masking_profile,
            "affected_column_count": (
                event.affected_column_count
            ),
            "referenced_institution_count": (
                event.referenced_institution_count
            ),
        }

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        with self._lock:
            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            file_descriptor = os.open(
                self.path,
                (
                    os.O_APPEND
                    | os.O_CREAT
                    | os.O_WRONLY
                ),
                0o600,
            )

            try:
                with os.fdopen(
                    file_descriptor,
                    "a",
                    encoding="utf-8",
                ) as handle:
                    handle.write(
                        serialized + "\n"
                    )
                    handle.flush()
                    os.fsync(
                        handle.fileno()
                    )
            except Exception:
                try:
                    os.close(
                        file_descriptor
                    )
                except OSError:
                    pass
                raise

            try:
                os.chmod(
                    self.path,
                    0o600,
                )
            except OSError:
                pass


def _sha256(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()
