from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import delete

from app.api.deps import CurrentUser, Impersonator, SessionDep
from app.core.audit import record_event
from app.core.crypto import crypto_configured, decrypt, encrypt
from app.core.rate_limit import client_ip
from app.core.security import hash_token
from app.core.two_factor import (
    consume_valid_code,
    generate_recovery_codes,
    generate_secret,
    provisioning_uri,
    qr_data_uri,
    verify_totp,
)
from app.models import AuditAction, TwoFactorChallenge, TwoFactorRecoveryCode, User
from app.schemas import (
    RecoveryCodesRead,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorSetupRead,
    UserRead,
)

router = APIRouter()

_UNAVAILABLE_DETAIL = "Two-factor authentication is temporarily unavailable"


def _require_crypto() -> None:
    """Every 2FA operation reads or writes the encrypted seed, so refuse (rather
    than crash) when no encryption key is configured."""
    if not crypto_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL
        )


async def _replace_recovery_codes(session: SessionDep, user: User) -> list[str]:
    """Drop any existing recovery codes and mint a fresh batch, storing only
    their hashes. Returns the plaintext codes to show the user once."""
    await session.execute(
        delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user.id)
    )
    codes = generate_recovery_codes()
    for code in codes:
        session.add(TwoFactorRecoveryCode(user_id=user.id, code_hash=hash_token(code)))
    return codes


@router.post("/setup", response_model=TwoFactorSetupRead)
async def setup_two_factor(user: CurrentUser, session: SessionDep) -> TwoFactorSetupRead:
    """Begin enrolment: generate a fresh secret (stored encrypted but not yet
    active) and return the QR / manual key. Confirm with a code to activate."""
    _require_crypto()
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor authentication is already enabled",
        )
    secret = generate_secret()
    user.totp_secret = encrypt(secret)
    await session.commit()
    uri = provisioning_uri(secret, user.email)
    return TwoFactorSetupRead(secret=secret, otpauth_uri=uri, qr=qr_data_uri(uri))


@router.post("/confirm", response_model=RecoveryCodesRead)
async def confirm_two_factor(
    payload: TwoFactorConfirmRequest,
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> RecoveryCodesRead:
    """Finish enrolment: verify a code from the just-scanned authenticator, then
    activate 2FA and hand back the one-time recovery codes."""
    _require_crypto()
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor authentication is already enabled",
        )
    if user.totp_secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start two-factor setup first",
        )
    if not verify_totp(decrypt(user.totp_secret), payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That code is not valid"
        )

    user.totp_enabled = True
    codes = await _replace_recovery_codes(session, user)
    await record_event(
        session,
        action=AuditAction.two_factor_enabled,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    return RecoveryCodesRead(recovery_codes=codes)


@router.post("/recovery-codes", response_model=RecoveryCodesRead)
async def regenerate_recovery_codes(
    payload: TwoFactorDisableRequest,
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> RecoveryCodesRead:
    """Replace the recovery codes with a fresh set (invalidating the old ones).
    Requires a valid current code to prove possession of the second factor."""
    _require_crypto()
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enabled",
        )
    if not await consume_valid_code(session, user, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That code is not valid"
        )
    codes = await _replace_recovery_codes(session, user)
    await record_event(
        session,
        action=AuditAction.two_factor_recovery_regenerated,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    return RecoveryCodesRead(recovery_codes=codes)


@router.post("/disable", response_model=UserRead)
async def disable_two_factor(
    payload: TwoFactorDisableRequest,
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    """Turn 2FA off. Requires a valid TOTP or recovery code (not the password),
    so only someone holding the second factor can remove it."""
    _require_crypto()
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enabled",
        )
    if not await consume_valid_code(session, user, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That code is not valid"
        )

    user.totp_secret = None
    user.totp_enabled = False
    await session.execute(
        delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.user_id == user.id)
    )
    await session.execute(delete(TwoFactorChallenge).where(TwoFactorChallenge.user_id == user.id))
    await record_event(
        session,
        action=AuditAction.two_factor_disabled,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(user)
    return user
