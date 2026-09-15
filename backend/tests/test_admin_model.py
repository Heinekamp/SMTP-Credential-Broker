import datetime

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.security import hash_password
from app.models.admin import AdminSession, AdminUser


def test_deleting_an_admin_cascades_sessions_via_the_orm(db_session: Session) -> None:
    """Regression test for the same class of bug fixed on Sender.permissions
    and LocalSmtpUser.permissions (issue #13): without passive_deletes=True,
    SQLAlchemy's ORM tries to null out admin_sessions.admin_user_id itself
    before deleting the parent, which fails because the column is
    nullable=False, instead of deferring to the DB's own ON DELETE CASCADE.
    There is no admin-delete route yet, so this exercises db.delete()
    directly — the same call any future delete route would make."""
    admin = AdminUser(email="doomed@example.com", password_hash=hash_password("x"))
    db_session.add(admin)
    db_session.commit()

    db_session.add(
        AdminSession(
            admin_user_id=admin.id,
            token_hash="a" * 64,
            expires_at=utcnow() + datetime.timedelta(hours=1),
        )
    )
    db_session.commit()

    db_session.delete(admin)
    db_session.commit()

    assert db_session.query(AdminSession).filter_by(admin_user_id=admin.id).count() == 0
