from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

# Emails are stored and compared lower-cased so a differently-cased address is
# the same account (L3). The validator runs only on the non-None union member,
# so an optional email left unset stays None.
NormalisedEmail = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    is_admin: bool
    is_active: bool
    created_at: datetime


class MeRead(UserRead):
    impersonating: bool = False


class UserCreate(BaseModel):
    email: NormalisedEmail
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8)
    is_admin: bool = False


class UserUpdate(BaseModel):
    email: NormalisedEmail | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=8)
    is_admin: bool | None = None
    is_active: bool | None = None


class LoginRequest(BaseModel):
    email: NormalisedEmail
    password: str
