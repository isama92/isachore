from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.auth_token import AuthToken
    from app.models.chore import Chore
    from app.models.confirmation_token import ConfirmationToken
    from app.models.household import Household


class UserStatus(StrEnum):
    """Account lifecycle. A user is created either waiting_confirmation (they
    set their own password via an emailed link) or active (an admin set the
    password directly); disabled is the soft-deleted / suspended state. Only an
    active user can log in or be impersonated."""

    waiting_confirmation = "waiting_confirmation"
    active = "active"
    disabled = "disabled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    # Filename of the user's uploaded avatar under <storage_dir>/avatars (not a
    # full path); None means "no picture, fall back to initials". Unique so two
    # users can never end up pointed at the same file (Postgres allows many
    # NULLs, so "no avatar" is unaffected).
    avatar_path: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)
    # Appearance preference: Catppuccin flavour + accent colour. NULL means "not
    # chosen", so the client falls back to the OS-preferred default. The allowed
    # values are a small closed set enforced at the schema layer, so a plain
    # String column (no DB enum) keeps future additions migration-free.
    theme: Mapped[str | None] = mapped_column(String(32), default=None)
    accent_color: Mapped[str | None] = mapped_column(String(32), default=None)
    # UI language preference. NULL means "not chosen", so the client falls back
    # to its default (English). Same closed-set-at-the-schema-layer approach as
    # theme/accent above.
    language: Mapped[str | None] = mapped_column(String(32), default=None)
    is_admin: Mapped[bool] = mapped_column(default=False)
    # Account lifecycle. Stored as a plain String (closed set enforced at the
    # schema layer, same approach as theme/accent/language above) so adding a
    # future status stays migration-free. StrEnum members compare equal to their
    # string value, so `user.status == UserStatus.active` works on the raw value.
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.active)
    # When the user completed account setup (set their password), whether via
    # the emailed confirmation link or an admin creating them active directly.
    # NULL means they never confirmed, so an admin forcing them active leaves a
    # visible "active but unconfirmed" warning in the UI.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Indexed because it is the default sort key for the admin users table.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tokens: Mapped[list["AuthToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    confirmation_tokens: Mapped[list["ConfirmationToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    households: Mapped[list["Household"]] = relationship(
        secondary="household_members", back_populates="members"
    )
    chores: Mapped[list["Chore"]] = relationship(
        secondary="chore_assignees", back_populates="assignees"
    )
