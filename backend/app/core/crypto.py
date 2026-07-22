"""Symmetric encryption of secrets at rest.

A general-purpose helper around Fernet (AES-128-CBC + HMAC) keyed by
``settings.app_key``. Used wherever a stored secret must be recoverable rather
than hashed; the first consumer is the 2FA TOTP seed, which has to be readable
to verify codes. The key is read lazily at call time (never at import) so the
app boots without it and tests can override ``settings.app_key`` by monkeypatch.
"""

from cryptography.fernet import Fernet

from app.core.config import settings

# Shared error detail when an encryption action is attempted without a key.
NO_APP_KEY_DETAIL = "Encryption is not configured (APP_KEY is unset)"


def _fernet() -> Fernet | None:
    """Build a Fernet from the configured key, or None if it is unset or
    malformed. A bad key reads as "unconfigured" so callers fail closed instead
    of raising an opaque error mid-flow."""
    key = settings.app_key
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        return None


def crypto_configured() -> bool:
    """Whether a usable encryption key is present. A missing OR malformed
    APP_KEY reads as not configured, so security-critical callers fail closed."""
    return _fernet() is not None


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning urlsafe-base64 ciphertext. Raises RuntimeError
    if no valid key is configured."""
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError(NO_APP_KEY_DETAIL)
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt ciphertext produced by ``encrypt``. Raises RuntimeError if no
    valid key is configured, or cryptography.fernet.InvalidToken if the
    ciphertext does not verify (wrong key or tampering)."""
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError(NO_APP_KEY_DETAIL)
    return fernet.decrypt(ciphertext.encode()).decode()
