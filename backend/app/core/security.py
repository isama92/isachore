import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from pwdlib import PasswordHash

from app.core.config import settings

TOKEN_TTL = timedelta(days=30)
# A login without "remember me" gets a browser-session cookie; this caps how
# long the matching DB token stays valid so a leaked token can't outlive it.
SESSION_TOKEN_TTL = timedelta(days=1)
# Account-confirmation links are longer-lived than a login session but still
# expire so a stale invite can't be redeemed indefinitely; the admin can resend.
CONFIRMATION_TOKEN_TTL = timedelta(days=1)
# Household invite links: short-lived so a leaked/stale link can't be redeemed
# indefinitely; the owner can mint another.
INVITATION_TOKEN_TTL = timedelta(hours=24)
COOKIE_NAME = "isachore_token"
# Holds the original admin session while impersonating another user
ADMIN_COOKIE_NAME = "isachore_admin_token"
# Holds a short-lived 2FA challenge between the password step and the code step
# of a two-step login. Short TTL: the user should enter their code promptly.
TWO_FACTOR_COOKIE_NAME = "isachore_2fa"
TWO_FACTOR_TTL = timedelta(minutes=5)
# Binds an in-flight SSO sign-on to the browser that started it: the same random
# value goes here and into the OAuth2 `state` parameter, and the callback requires
# the two to match. Longer TTL than the 2FA challenge because the user spends this
# window on someone else's login page, possibly completing an MFA step there.
#
# Deliberately NOT listed in app/core/csrf.py's _AUTH_COOKIES, for the same reason
# isachore_2fa is not: it authenticates nobody, so it must not turn an anonymous
# request into one the CSRF middleware treats as a session. (Listing it would not
# actually break today's flow, since that middleware only inspects unsafe methods and
# both OIDC endpoints are GET - but the flow being GET is not what makes this right.)
OIDC_STATE_COOKIE_NAME = "isachore_oidc"
OIDC_STATE_TTL = timedelta(minutes=10)

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


def set_auth_cookie(
    response: Response,
    token: str,
    name: str = COOKIE_NAME,
    max_age: int | None = int(TOKEN_TTL.total_seconds()),
) -> None:
    # max_age=None emits a session cookie (Starlette omits the Max-Age
    # attribute), which browsers drop at the end of the session; the login route
    # also caps the matching token at a day so it can't linger. The default
    # keeps the 30-day persistent behaviour every existing caller relies on.
    response.set_cookie(
        name,
        token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookies_secure,
    )


def clear_auth_cookie(response: Response, name: str = COOKIE_NAME) -> None:
    # Mirror the attributes used when setting the cookie: browsers are
    # increasingly strict about matching path/SameSite/Secure on removal, and a
    # mismatch can leave the cookie un-cleared (L4).
    response.delete_cookie(
        name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookies_secure,
    )
