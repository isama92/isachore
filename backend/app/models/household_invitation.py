from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.household import Household
    from app.models.user import User


class HouseholdInvitationStatus(StrEnum):
    """Stored lifecycle of an invitation. "expired" is NOT stored — it's a
    frontend display state for a `pending` invite whose token has passed
    `expires_at`. Stored as a plain String (closed set enforced at the schema
    layer, like UserStatus)."""

    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class HouseholdInvitation(Base):
    """A link inviting an existing user to join a household.

    Unlike confirmation/auth tokens, the raw token is stored (not hashed) so the
    owner can re-copy the link from the invitations list. It's short-lived (24h)
    and single-use (redeeming flips it to `accepted`, so it can't be reused),
    which bounds that exposure.
    """

    __tablename__ = "household_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    household_id: Mapped[int] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default=HouseholdInvitationStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    household: Mapped["Household"] = relationship()
    inviter: Mapped["User"] = relationship()
