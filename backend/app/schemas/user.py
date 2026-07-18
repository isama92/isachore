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


class MeRead(UserRead):
    impersonating: bool = False


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
            raise ValueError("current_password is required to set a new password")
        return self


class ConfirmTokenInfo(BaseModel):
    """Public info returned for a valid confirmation token so the set-password
    page can greet the user before they submit."""

    email: str
    first_name: str
    last_name: str


class ConfirmRequest(BaseModel):
    password: str = Field(min_length=8)
