"""TOTP two-factor helpers: secrets, provisioning URIs/QR, and code checking.

The TOTP seed is stored Fernet-encrypted (app.core.crypto) because it must be
recoverable to verify codes. Recovery codes are stored only as SHA-256 hashes
(like auth/confirmation tokens) and are single-use.
"""

import base64
import io
from datetime import UTC, datetime

import pyotp
import qrcode
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt
from app.core.security import generate_token, hash_token
from app.models import TwoFactorRecoveryCode, User

# How many backup codes to hand out at enrolment / regeneration.
RECOVERY_CODE_COUNT = 10
# ±1 step (30s) tolerance for clock skew between server and authenticator app.
_TOTP_VALID_WINDOW = 1


def generate_secret() -> str:
    """A fresh base32 TOTP secret (the value shown/scanned during setup)."""
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    """otpauth:// URI encoded into the setup QR and offered as a manual key."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.totp_issuer)


def qr_data_uri(uri: str) -> str:
    """Render the provisioning URI as a base64 PNG data URI so the SPA can show
    it in a plain <img> with no client-side QR dependency."""
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def verify_totp(secret: str, code: str) -> bool:
    """Whether code is a currently-valid TOTP for secret (with skew tolerance)."""
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=_TOTP_VALID_WINDOW)


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """A batch of high-entropy single-use backup codes (plaintext, shown once)."""
    return [generate_token()[:12] for _ in range(count)]


async def consume_valid_code(session: AsyncSession, user: User, code: str) -> bool:
    """Whether code authenticates the user via their TOTP secret OR an unused
    recovery code. A matching recovery code is consumed (used_at stamped) so it
    can never be replayed; the caller commits. A wrong code changes nothing.

    If the seed can't be decrypted (e.g. APP_KEY was rotated after enrolment),
    the TOTP branch is skipped rather than raising, so recovery codes still work
    as the escape hatch — they're hashed independently of the encrypted seed."""
    code = code.strip()
    if user.totp_secret is not None:
        try:
            if verify_totp(decrypt(user.totp_secret), code):
                return True
        except InvalidToken:
            pass
    result = await session.execute(
        select(TwoFactorRecoveryCode).where(
            TwoFactorRecoveryCode.user_id == user.id,
            TwoFactorRecoveryCode.code_hash == hash_token(code),
            TwoFactorRecoveryCode.used_at.is_(None),
        )
    )
    recovery = result.scalar_one_or_none()
    if recovery is not None:
        recovery.used_at = datetime.now(UTC)
        return True
    return False
