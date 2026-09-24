"""The single source of truth for "what's currently wrong" — used by both
GET /api/alerts (the notification bell) and the alert-email edge-trigger
loop (#9), so there's exactly one place that decides what counts as an
active alert. Every alert is computed fresh from existing state on every
call — nothing here is itself persisted as an "event" (background_job_state
only tracks enough last-seen state to edge-trigger email, not the alerts
themselves)."""

import dataclasses
import datetime
from importlib.metadata import version

from sqlalchemy.orm import Session

from app.core import postfix_control
from app.core.clock import utcnow
from app.core.health import run_health_check
from app.core.settings_store import get_background_job_state, get_relay_settings
from app.core.update_check import parse_version
from app.models.enums import TestResult
from app.models.local_user import LocalSmtpUser
from app.models.upstream import UpstreamAccount


@dataclasses.dataclass
class Alert:
    kind: str
    key: str
    title: str
    detail: str
    target_type: str | None = None
    target_id: int | None = None
    acknowledgeable: bool = False
    acknowledged: bool = False


def _update_alert(
    *,
    kind: str,
    title_prefix: str,
    installed_version: str | None,
    latest_version: str | None,
    acknowledged_version: str | None,
) -> Alert | None:
    if latest_version is None or installed_version is None:
        return None
    latest = parse_version(latest_version)
    installed = parse_version(installed_version)
    if latest is None or installed is None or latest <= installed:
        return None
    acknowledged = latest_version == acknowledged_version
    return Alert(
        kind=kind,
        key=kind,
        title=f"{title_prefix} update available",
        detail=f"{installed_version} installed, {latest_version} available",
        acknowledgeable=True,
        acknowledged=acknowledged,
    )


def compute_active_alerts(db: Session) -> list[Alert]:
    alerts: list[Alert] = []

    health = run_health_check(db)
    if health.status != "ok":
        alerts.append(
            Alert(
                kind="health_degraded",
                key="health_degraded",
                title="Relay is degraded",
                detail="See Settings → System for details.",
            )
        )

    failing_accounts = (
        db.query(UpstreamAccount).filter(UpstreamAccount.last_test_result == TestResult.failure).all()
    )
    for account in failing_accounts:
        alerts.append(
            Alert(
                kind="upstream_test_failure",
                key=f"upstream_test_failure:{account.id}",
                title=f'Upstream account "{account.name}" is failing its connection test',
                detail=account.last_test_error or "",
                target_type="upstream_account",
                target_id=account.id,
            )
        )

    settings_row = get_relay_settings(db)
    cutoff = utcnow() - datetime.timedelta(minutes=settings_row.rate_limit_abuse_threshold_minutes)
    throttled_users = (
        db.query(LocalSmtpUser)
        .filter(
            LocalSmtpUser.rate_limit_defer_streak_started_at.is_not(None),
            LocalSmtpUser.rate_limit_defer_streak_started_at <= cutoff,
        )
        .all()
    )
    for user in throttled_users:
        since = user.rate_limit_defer_streak_started_at
        if user.enabled:
            detail = (
                f"No messages have gone through since {since:%Y-%m-%d %H:%M} UTC — investigate before it "
                "exhausts a shared upstream mailbox's tolerance."
            )
        else:
            detail = (
                f"Automatically disabled after being throttled continuously since {since:%Y-%m-%d %H:%M} UTC. "
                "Re-enable it once the underlying issue is fixed."
            )
        alerts.append(
            Alert(
                kind="rate_limit_abuse",
                key=f"rate_limit_abuse:{user.id}",
                title=f'Local user "{user.name}" is being throttled continuously',
                detail=detail,
                target_type="local_smtp_user",
                target_id=user.id,
            )
        )

    state = get_background_job_state(db)

    app_alert = _update_alert(
        kind="app_update_available",
        title_prefix="SMTP Credential Broker",
        installed_version=version("relay"),
        latest_version=state.latest_app_version,
        acknowledged_version=state.app_update_acknowledged_version,
    )
    if app_alert is not None:
        alerts.append(app_alert)

    try:
        installed_postfix_version = postfix_control.version()
    except postfix_control.PostfixControlError:
        installed_postfix_version = None

    postfix_alert = _update_alert(
        kind="postfix_update_available",
        title_prefix="Postfix",
        installed_version=installed_postfix_version,
        latest_version=state.latest_postfix_version,
        acknowledged_version=state.postfix_update_acknowledged_version,
    )
    if postfix_alert is not None:
        alerts.append(postfix_alert)

    return alerts
