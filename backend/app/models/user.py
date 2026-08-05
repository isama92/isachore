from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.auth_token import AuthToken
    from app.models.chore import Chore
    from app.models.confirmation_token import ConfirmationToken
    from app.models.household import Household
    from app.models.two_factor_challenge import TwoFactorChallenge
    from app.models.two_factor_recovery_code import TwoFactorRecoveryCode


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
    # Two-factor auth (TOTP). totp_secret is the Fernet-encrypted seed (the seed
    # must be recoverable to verify codes, so it is encrypted at rest, not
    # hashed); NULL means never enrolled. totp_enabled gates the two-step login:
    # a secret can exist while disabled (a pending, not-yet-confirmed enrolment),
    # so login enforcement keys on totp_enabled, never on the secret's presence.
    totp_secret: Mapped[str | None] = mapped_column(String(255), default=None)
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    # Link to an external OpenID Connect identity, written on the first SSO sign-in
    # (see api/v1/oidc.py). NULL on both means "never signed in through a provider",
    # which is every account until it does; a linked account can still use its
    # password, so this grants a second way in rather than replacing the first.
    #
    # BOTH columns, not just the subject, and the unique constraint spans the pair.
    # `sub` is only promised to be unique *per issuer*, so with the subject alone an
    # operator who repointed OIDC_ISSUER at a different provider whose subject values
    # happened to collide would have handed one person another's account. Storing the
    # issuer makes that lookup simply miss, falling back to matching on email, which
    # re-links correctly. Note nothing enforces that these match the *currently*
    # configured issuer: a stale link is inert rather than dangerous, because the
    # lookup is keyed on the pair.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), default=None)
    oidc_issuer: Mapped[str | None] = mapped_column(String(255), default=None)
    # Indexed because it is the default sort key for the admin users table.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # One local account per external identity. Postgres treats NULLs as distinct,
        # so every account that has never used SSO (both columns NULL) is exempt, which
        # is what makes this safe to add to an existing table.
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
    )

    tokens: Mapped[list["AuthToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    confirmation_tokens: Mapped[list["ConfirmationToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    two_factor_challenges: Mapped[list["TwoFactorChallenge"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    recovery_codes: Mapped[list["TwoFactorRecoveryCode"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    households: Mapped[list["Household"]] = relationship(
        secondary="household_members", back_populates="members"
    )
    chores: Mapped[list["Chore"]] = relationship(
        secondary="chore_assignees", back_populates="assignees"
    )
