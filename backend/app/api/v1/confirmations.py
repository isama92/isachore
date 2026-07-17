from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.api.deps import SessionDep
from app.core.audit import record_event
from app.core.rate_limit import client_ip
from app.core.security import (
    TOKEN_TTL,
    generate_token,
    hash_password,
    hash_token,
    set_auth_cookie,
)
from app.core.tokens import purge_expired_confirmation_tokens
from app.models import AuditAction, AuthToken, ConfirmationToken, User, UserStatus
from app.schemas import ConfirmRequest, ConfirmTokenInfo, UserRead

router = APIRouter()

_invalid_token_exc = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired confirmation link"
)


async def _resolve_token(session: SessionDep, token: str) -> ConfirmationToken | None:
    """Look up a non-expired confirmation token by its hash, with the user
    eager-loaded. Returns None for an unknown or expired token."""
    result = await session.execute(
        select(ConfirmationToken)
        .options(joinedload(ConfirmationToken.user))
        .where(
            ConfirmationToken.token_hash == hash_token(token),
            ConfirmationToken.expires_at > datetime.now(UTC),
        )
    )
    return result.scalar_one_or_none()


@router.get("/{token}", response_model=ConfirmTokenInfo)
async def confirmation_info(token: str, session: SessionDep) -> User:
    """Validate a confirmation link so the set-password page can greet the user
    (or show an invalid/expired state) before they submit."""
    confirmation = await _resolve_token(session, token)
    if confirmation is None:
        raise _invalid_token_exc
    return confirmation.user


@router.post("/{token}", response_model=UserRead)
async def confirm_account(
    token: str,
    payload: ConfirmRequest,
    session: SessionDep,
    request: Request,
    response: Response,
) -> User:
    """Set the user's password from the confirmation link, activate the account,
    consume the token, and log the user straight in."""
    confirmation = await _resolve_token(session, token)
    if confirmation is None:
        raise _invalid_token_exc

    user = confirmation.user
    user.password_hash = hash_password(payload.password)
    user.status = UserStatus.active
    user.confirmed_at = datetime.now(UTC)
    # Consume every confirmation token for this user so the link is single-use.
    await session.execute(delete(ConfirmationToken).where(ConfirmationToken.user_id == user.id))
    await purge_expired_confirmation_tokens(session)

    # Auto-login: they proved control of the mailbox and just set a password.
    auth_token = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(auth_token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + TOKEN_TTL,
        )
    )
    await record_event(
        session,
        action=AuditAction.user_confirmed,
        actor_id=user.id,
        target_id=user.id,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(user)

    set_auth_cookie(response, auth_token)
    return user
