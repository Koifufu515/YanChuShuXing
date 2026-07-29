from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.application.models import AuditEvent


@dataclass(frozen=True)
class SecurityAlert:
    alert_type: str
    severity: str
    event_count: int
    window_seconds: int
    security_action: str


@dataclass(frozen=True)
class _AlertRule:
    alert_type: str
    severity: str
    threshold: int
    window_seconds: int
    security_action: str


class SecurityAlertMonitor:
    """
    根据进程内审计事件识别短时间安全异常。

    本类只负责业务判定，不写文件、不发送通知，也不持久化用户标识。
    """

    def __init__(
        self,
        *,
        cooldown_seconds: int = 600,
    ) -> None:
        if cooldown_seconds < 0:
            raise ValueError(
                "告警冷却时间不能为负数。"
            )

        self.cooldown_seconds = (
            cooldown_seconds
        )
        self._event_windows: dict[
            tuple[str, str],
            deque[datetime],
        ] = defaultdict(deque)
        self._last_alert_at: dict[
            tuple[str, str],
            datetime,
        ] = {}

    def evaluate(
        self,
        event: AuditEvent,
        *,
        occurred_at: datetime | None = None,
    ) -> list[SecurityAlert]:
        timestamp = occurred_at or datetime.now(
            timezone.utc
        )

        if timestamp.tzinfo is None:
            raise ValueError(
                "告警事件时间必须包含时区。"
            )

        actor_key = event.user_id or "anonymous"
        alerts: list[SecurityAlert] = []

        for rule in self._matching_rules(event):
            key = (
                rule.alert_type,
                actor_key,
            )
            window = self._event_windows[key]
            cutoff = timestamp - timedelta(
                seconds=rule.window_seconds
            )

            while window and window[0] < cutoff:
                window.popleft()

            window.append(timestamp)

            if len(window) < rule.threshold:
                continue

            last_alert = self._last_alert_at.get(
                key
            )

            if (
                last_alert is not None
                and timestamp - last_alert
                < timedelta(
                    seconds=self.cooldown_seconds
                )
            ):
                continue

            self._last_alert_at[key] = timestamp

            alerts.append(
                SecurityAlert(
                    alert_type=rule.alert_type,
                    severity=rule.severity,
                    event_count=len(window),
                    window_seconds=(
                        rule.window_seconds
                    ),
                    security_action=(
                        rule.security_action
                    ),
                )
            )

        return alerts

    @staticmethod
    def _matching_rules(
        event: AuditEvent,
    ) -> list[_AlertRule]:
        rules: list[_AlertRule] = []

        if (
            event.event_type
            == "authentication_failed"
            and event.security_action
            in {
                "authentication_required",
                "invalid_bearer_token",
            }
        ):
            rules.append(
                _AlertRule(
                    alert_type=(
                        "repeated_authentication_failure"
                    ),
                    severity="medium",
                    threshold=5,
                    window_seconds=300,
                    security_action=(
                        "authentication_failure_threshold"
                    ),
                )
            )

        if (
            event.security_action
            == "institution_scope_denied"
        ):
            rules.append(
                _AlertRule(
                    alert_type=(
                        "repeated_institution_scope_denial"
                    ),
                    severity="high",
                    threshold=3,
                    window_seconds=600,
                    security_action=(
                        "institution_denial_threshold"
                    ),
                )
            )

        if event.event_type in {
            "authentication_failed",
            "access_denied",
        }:
            rules.append(
                _AlertRule(
                    alert_type=(
                        "high_frequency_security_denial"
                    ),
                    severity="critical",
                    threshold=10,
                    window_seconds=60,
                    security_action=(
                        "security_denial_rate_threshold"
                    ),
                )
            )

        return rules
