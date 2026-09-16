from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ApiToken(Base):
    """A user's personal access token: one long-lived credential for a client with
    no browser, such as a Home Assistant integration polling the due list.

    A table of its own rather than a row in auth_tokens. Three statements delete a
    user's sessions by user_id - the self-service password change (api/v1/profile.py),
    admin_users._revoke_tokens, which serves both the admin password reset and
    deactivation, and the CLI's admin recovery - and purge_expired_tokens sweeps the
    rest by expires_at, which a row with no expiry would need an exception for too.
    Living here means none of them can take this row by accident, which auth.md warns
    is how a stale way in survives. Two of them take it on purpose anyway: see
    admin_users._revoke_tokens for why those are not the routine case.

    The remaining deletions against auth_tokens target one token_hash (logout,
    impersonation, stop-impersonating) and so are confined to that table regardless.

    No expires_at, because it never expires. No last_used_at: it is not tracked, so
    the audit trail records that a token was made and revoked but never that it was
    used. No label, because there is at most one.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Unique, so "one per user" is unrepresentable rather than merely checked: the
    # create endpoint inserts and catches IntegrityError instead of reading first,
    # which also closes the double-POST race a check-then-insert would leave open.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="api_token")
