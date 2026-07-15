import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from pwdlib import PasswordHash

from app.core.config import settings

TOKEN_TTL = timedelta(days=30)
COOKIE_NAME = "isachore_token"
# Holds the original admin session while impersonating another user
ADMIN_COOKIE_NAME = "isachore_admin_token"

_password_hash = PasswordHash.recommended()

# Verified against when a login email doesn't exist, so both branches cost
# one argon2 verification and response timing can't leak which emails exist.
DUMMY_PASSWORD_HASH = _password_hash.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def set_auth_cookie(response: Response, token: str, name: str = COOKIE_NAME) -> None:
    response.set_cookie(
        name,
        token,
        max_age=int(TOKEN_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.environment != "dev",
    )


def clear_auth_cookie(response: Response, name: str = COOKIE_NAME) -> None:
    response.delete_cookie(name, path="/")
