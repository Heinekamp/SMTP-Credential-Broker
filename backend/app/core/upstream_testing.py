"""Shared "persist a connection-test result onto an account" logic, used
by both the manual Test Connection route (upstream_accounts.py) and the
scheduled batch (scheduled_tests.py) so the two paths can't drift."""

from app.core.clock import utcnow
from app.core.test_connection import TestConnectionResult
from app.models.enums import TestResult
from app.models.upstream import UpstreamAccount


def apply_test_result(account: UpstreamAccount, result: TestConnectionResult) -> None:
    account.last_test_at = utcnow()
    account.last_test_result = TestResult.success if result.success else TestResult.failure
    account.last_test_error = (
        None
        if result.success
        else "; ".join(f"{step.name}: {step.detail}" for step in result.steps if not step.passed)
    )
