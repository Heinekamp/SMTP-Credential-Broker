"""Import every model module so Base.metadata is complete before Alembic
autogenerates a migration, and so `from app.models import X` works as a
single import surface for the rest of the app."""

from app.models.admin import AdminSession, AdminUser
from app.models.audit import AuditLog
from app.models.config_generation import ConfigGeneration
from app.models.enums import MailStatus, TestResult, TlsMode, ValidationResult
from app.models.local_user import LocalSmtpUser, UserSenderPermission
from app.models.mail_log import MailLog, MailLogIngestState
from app.models.rate_limit import LocalUserBurstBucket, LocalUserRateLimitCounter
from app.models.sender import Sender
from app.models.settings import BackgroundJobState, RelaySettings
from app.models.tls import TlsCertificateState
from app.models.upstream import UpstreamAccount

__all__ = [
    "AdminUser",
    "AdminSession",
    "AuditLog",
    "ConfigGeneration",
    "MailStatus",
    "TestResult",
    "TlsMode",
    "ValidationResult",
    "LocalSmtpUser",
    "UserSenderPermission",
    "MailLog",
    "MailLogIngestState",
    "LocalUserRateLimitCounter",
    "LocalUserBurstBucket",
    "Sender",
    "BackgroundJobState",
    "RelaySettings",
    "TlsCertificateState",
    "UpstreamAccount",
]
