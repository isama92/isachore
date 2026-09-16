from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ApiTokenRead(BaseModel):
    """What is knowable about an access token after it is made. Not the token: only its
    SHA-256 is stored, so the plaintext exists nowhere once creation has answered."""

    model_config = ConfigDict(from_attributes=True)

    created_at: datetime


class ApiTokenStatusRead(BaseModel):
    """Whether the caller holds an access token, and when they made it.

    A wrapper round a nullable member rather than a nullable body or a 404. Holding no
    token is the normal state of every account that has never made one, so a 404 would
    make the Profile page's ordinary first render an error - and a top-level JSON null
    forces `T | null` on every client call site for nothing. LoginResponse.user is the
    same shape for the same reason.
    """

    token: ApiTokenRead | None = None


class ApiTokenCreate(BaseModel):
    # Optional rather than required so a missing field and a wrong password give one
    # answer, the 400 below, instead of splitting into a 422 the frontend would have to
    # parse differently. ProfileUpdate.current_password is typed the same way.
    current_password: str | None = None


class ApiTokenCreated(ApiTokenRead):
    """The one response that carries the token itself. Shown once and never again:
    nothing reads it back, because nothing can."""

    token: str
