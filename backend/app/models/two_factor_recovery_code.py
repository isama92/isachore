from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class TwoFactorRecoveryCode(Base):
    """A single-use backup code that can substitute for a TOTP code at login.
    Only the SHA-256 hash is stored (like auth/confirmation tokens); the
    plaintext is shown to the user once at generation. Consumption stamps
    used_at rather than deleting the row, so a used code can never be replayed.
    Lookups are always scoped to a user_id, so the hash need not be globally
    unique."""

    __tablename__ = "two_factor_recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="recovery_codes")
