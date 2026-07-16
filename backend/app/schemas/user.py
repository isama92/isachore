from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    model_validator,
)

# Emails are stored and compared lower-cased so a differently-cased address is
# the same account (L3). The validator runs only on the non-None union member,
# so an optional email left unset stays None.
NormalisedEmail = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str
    last_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime
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
    password: str = Field(min_length=8)
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: NormalisedEmail | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8)
    is_admin: bool | None = None
    is_active: bool | None = None


class LoginRequest(BaseModel):
    email: NormalisedEmail
    password: str


class ProfileUpdate(BaseModel):
    """Self-service profile edit. Changing the password requires the current one
    (the confirm-new-password field is a frontend-only check; the API takes the
    old and new passwords only)."""

    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    last_name: str | None = Field(default=None, min_length=1, max_length=255)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8)

    @model_validator(mode="after")
    def _password_pair(self) -> "ProfileUpdate":
        if self.new_password is not None and not self.current_password:
            raise ValueError("current_password is required to set a new password")
        return self
