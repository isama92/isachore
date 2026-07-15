import hashlib
import secrets
from datetime import timedelta

from pwdlib import PasswordHash

TOKEN_TTL = timedelta(days=30)
COOKIE_NAME = "isachore_token"

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
