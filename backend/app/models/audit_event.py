import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(enum.StrEnum):
    login_success = "login_success"
    login_failed = "login_failed"
    logout = "logout"
    impersonate_start = "impersonate_start"
    impersonate_stop = "impersonate_stop"
    user_created = "user_created"
    user_updated = "user_updated"
    user_deactivated = "user_deactivated"
    user_confirmed = "user_confirmed"


class AuditEvent(Base):
    """Append-only audit trail for authentication, impersonation and admin
    user-management actions (M3). Records who did what, to whom, from where and
    when; impersonator_user_id preserves accountability so an action taken while
    impersonating always traces back to the real operator."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[AuditAction] = mapped_column(SAEnum(AuditAction, name="audit_action"))
    # Nullable + SET NULL (a deliberate departure from the usual CASCADE) so the
    # trail survives a hypothetical hard user delete; login_failed also has no
    # known actor.
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # The real admin behind an impersonated session, when the action was taken
    # while impersonating.
    impersonator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    detail: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
