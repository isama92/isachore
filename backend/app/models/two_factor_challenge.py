from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class TwoFactorChallenge(Base):
    """Short-lived record of a login that cleared the password step and is
    awaiting a 2FA code. Mirrors ConfirmationToken: only the SHA-256 hash is
    stored, the raw token rides in the httpOnly isachore_2fa cookie. Carries the
    step-1 "remember me" choice so the final auth token gets the right TTL.
    Deleted on successful verification or expiry (a wrong code keeps it, so a
    typo doesn't force a fresh password entry)."""

    __tablename__ = "two_factor_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    remember: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="two_factor_challenges")
