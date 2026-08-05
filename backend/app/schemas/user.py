from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    model_validator,
)

from app.models.household import HouseholdRole
from app.models.user import UserStatus

# Emails are stored and compared lower-cased so a differently-cased address is
# the same account (L3). The validator runs only on the non-None union member,
# so an optional email left unset stays None.
NormalisedEmail = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]

# Appearance preference value sets, kept in sync with the frontend theme module
# (frontend/src/theme). A Literal both documents the closed set and makes an
# unknown value a 422 on write.
Flavour = Literal["latte", "frappe", "macchiato", "mocha"]
Accent = Literal[
    "rosewater",
    "flamingo",
    "pink",
    "mauve",
    "red",
    "maroon",
    "peach",
    "yellow",
    "green",
    "teal",
    "sky",
    "sapphire",
    "blue",
    "lavender",
]
# UI language, kept in sync with the frontend i18n module (frontend/src/i18n).
Language = Literal["en", "it"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str
    last_name: str
    is_admin: bool
    status: UserStatus
    # When the user completed setup; None means they never confirmed. Drives the
    # "active but unconfirmed" warning in the admin UI.
    confirmed_at: datetime | None = None
    created_at: datetime
    # Appearance preference; None means the client follows its OS-preferred
    # default (the SPA applies these on load).
    theme: Flavour | None = None
    accent_color: Accent | None = None
    # UI language; None means the client uses its default (English).
    language: Language | None = None
    # Whether TOTP two-factor auth is enrolled and active. Read from the ORM's
    # totp_enabled column (the secret itself is never exposed); serialised under
    # the clearer two_factor_enabled name the client uses.
    two_factor_enabled: bool = Field(default=False, validation_alias="totp_enabled")
    # Raw stored filename, read from the ORM object but never serialised; the
    # client only ever sees the derived avatar_url below.
    avatar_path: str | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def avatar_url(self) -> str | None:
        """URL the SPA can load the avatar from. Served by the StaticFiles mount
        at /api/v1/media (proxied untouched by the prod nginx /api rule)."""
        if not self.avatar_path:
            return None
        return f"/api/v1/media/avatars/{self.avatar_path}"


class MembershipRead(BaseModel):
    """One of the caller's household memberships: which household, what they may do in it,
    and whether they own *this* household (not whether they own any).

    Ownership is `households.admin_id`, a separate fact from the role ladder rather than a
    rung on it: the owner is always an organiser, but not every organiser owns. It rides here
    because the sidebar has to decide whether to offer the Logs page before any household has
    been fetched."""

    household_id: int
    role: HouseholdRole
    owned: bool


class MeRead(UserRead):
    impersonating: bool = False
    # Every active household the caller belongs to, with their role. Here rather than on
    # the household payloads because the sidebar has to decide what to show before any
    # household has been fetched, and this response is already loaded once on mount. It
    # is a convenience for the UI only: the roles are re-checked on every request, so a
    # stale copy (someone changed your role mid-session) hides or shows the wrong nav
    # item until the next /auth/me, and grants nothing.
    memberships: list[MembershipRead] = []
    # Whether this server asks new accounts to confirm their address
    # (`app_settings.require_confirmation`). Server-wide rather than personal, and here
    # because it is what tells a client how to read this payload's own `confirmed_at`: a
    # null on a server that never asks for confirmation means nothing, while on one that
    # does it means the address has not been proved. The Profile page shows the badge only
    # when this is true. Admins read the same flag from /settings, which is where it is
    # editable; this copy is read-only and carries no other server configuration.
    email_confirmation_required: bool = False


class UserCreate(BaseModel):
    email: NormalisedEmail
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str = Field(min_length=1, max_length=255)
    # Optional: required only when confirmation is off (admin sets it); when
    # confirmation is on the user sets it via the emailed link, so it's ignored.
    password: str | None = Field(default=None, min_length=8)
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: NormalisedEmail | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8)
    is_admin: bool | None = None
    status: UserStatus | None = None


class LoginRequest(BaseModel):
    email: NormalisedEmail
    password: str
    # When true, the session persists across browser restarts (a long-lived
    # cookie + token); when false (the default) it's a browser-session cookie.
    remember: bool = False


class ProfileUpdate(BaseModel):
    """Self-service profile edit. Changing the password requires the current one
    (the confirm-new-password field is a frontend-only check; the API takes the
    old and new passwords only)."""

    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8)
    theme: Flavour | None = None
    accent_color: Accent | None = None
    language: Language | None = None

    @model_validator(mode="after")
    def _password_pair(self) -> "ProfileUpdate":
        if self.new_password is not None and not self.current_password:
            # User-facing copy, not a developer message: a `value_error` is passed through
            # verbatim by the frontend's 422 formatter (see the note in schemas/chore.py).
            raise ValueError("Your current password is required to set a new one")
        return self


class ConfirmTokenInfo(BaseModel):
    """Public info returned for a valid confirmation token so the set-password
    page can greet the user before they submit."""

    email: str
    first_name: str
    last_name: str


class ConfirmRequest(BaseModel):
    password: str = Field(min_length=8)


class LoginResponse(BaseModel):
    """Outcome of the password step. When two_factor_required is False the user
    is fully logged in and `user` is populated; when True a short-lived 2FA
    challenge cookie has been set and the client must POST the code to
    /auth/verify-2fa (user is None until then)."""

    two_factor_required: bool = False
    # MeRead rather than UserRead so the client gets the caller's household memberships
    # with the session it just opened; the sidebar reads them, and refetching /auth/me
    # right after logging in would be a round trip to learn something login already knew.
    user: MeRead | None = None


# A submitted 2FA code: a 6-digit TOTP or a backup recovery code. Kept loose
# (min 1) so the endpoint returns a clean 401 "invalid code" rather than a 422
# for a wrong-length guess; the upper bound just caps abuse.
class TwoFactorCode(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class TwoFactorVerifyRequest(TwoFactorCode):
    """Code submitted at the login verify step."""


class TwoFactorConfirmRequest(TwoFactorCode):
    """Code confirming an authenticator was set up correctly (enable)."""


class TwoFactorDisableRequest(TwoFactorCode):
    """Code proving possession of the second factor when disabling / regenerating."""


class TwoFactorSetupRead(BaseModel):
    """Everything the setup UI needs to enrol an authenticator."""

    secret: str
    otpauth_uri: str
    qr: str  # base64 PNG data URI


class RecoveryCodesRead(BaseModel):
    """The one-time backup codes, returned once at enable / regeneration."""

    recovery_codes: list[str]
