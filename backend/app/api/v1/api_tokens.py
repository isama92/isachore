"""The one personal access token an account may hold, generated and revoked by its owner.

Session-gated, deliberately: an access token cannot manage access tokens, which is why
every handler here takes `CurrentUser` rather than `ApiUser`.
"""

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, Impersonator, SessionDep
from app.api.responses import refusals
from app.core.api_tokens import api_token_status, new_api_token, revoke_api_token
from app.core.audit import record_event
from app.core.rate_limit import client_ip
from app.core.security import hash_token, verify_password
from app.models import ApiToken, AuditAction
from app.schemas import ApiTokenCreate, ApiTokenCreated, ApiTokenStatusRead

router = APIRouter()

_already_exists_exc = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="You already have an access token. Delete it before generating a new one.",
)


@router.get("", response_model=ApiTokenStatusRead)
async def read_api_token(user: CurrentUser, session: SessionDep) -> ApiTokenStatusRead:
    """Whether this account holds an access token, and when it was made. Never the
    token: only its hash is stored, so there is nothing to return."""
    return await api_token_status(session, user.id)


@router.post(
    "",
    response_model=ApiTokenCreated,
    status_code=status.HTTP_201_CREATED,
    responses=refusals(
        (
            status.HTTP_400_BAD_REQUEST,
            "The current password is wrong, or none was given. Generating a token needs it.",
        ),
        (
            status.HTTP_403_FORBIDDEN,
            "An administrator impersonating this account cannot generate its access token.",
        ),
        (
            status.HTTP_409_CONFLICT,
            "This account already holds an access token. Delete that one before generating "
            "another; an account may hold only one.",
        ),
    ),
)
async def create_api_token(
    payload: ApiTokenCreate,
    user: CurrentUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> ApiTokenCreated:
    """Generate this account's access token and return it once.

    The current password is asked for the same reason the password change form asks: a
    stolen session or an injected script should not be able to mint a credential that
    outlives the session it was stolen from. Note what that does NOT cover - it is a
    check on the caller, not a throttle, and it is no more rate-limited here than the
    identical check in PATCH /profile.

    The 409 comes from the unique constraint rather than from reading first, so two
    requests racing cannot both succeed.

    Refused outright while impersonating, which is the one thing here that is not about the
    password. Impersonation ends; this credential does not, so minting one through it would
    turn temporary access to somebody's account into permanent access, and the owner would
    only find out by opening this page. An administrator who has reset the password could
    otherwise reach it - noisily, since both steps are audited, but noisy is not the same as
    refused.
    """
    if impersonator is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "An access token cannot be generated while impersonating. It would outlive "
                "the impersonation; ask the account holder to generate their own."
            ),
        )
    if not verify_password(payload.current_password or "", user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    raw = new_api_token()
    api_token = ApiToken(user_id=user.id, token_hash=hash_token(raw))
    session.add(api_token)
    try:
        # Flush rather than commit, so the constraint refuses before record_event runs:
        # that helper emits its log line the moment it is called, whatever the
        # transaction does afterwards, and an operator log claiming a token was created
        # where none was is worse than one round trip. Both writes still land together.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise _already_exists_exc from None
    await session.refresh(api_token)
    # No detail. It is the only field on an audit row a token could end up in.
    await record_event(
        session,
        action=AuditAction.api_token_created,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    return ApiTokenCreated(token=raw, created_at=api_token.created_at)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=refusals(
        (
            status.HTTP_404_NOT_FOUND,
            "This account holds no access token, so there is nothing to delete.",
        ),
    ),
)
async def delete_api_token(
    user: CurrentUser, impersonator: Impersonator, session: SessionDep, request: Request
) -> None:
    """Revoke this account's access token. No password, unlike generating one: revoking
    a credential is the safe direction, and it is the action you want to be easy when
    the token is the thing that leaked."""
    if not await revoke_api_token(session, user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="You have no access token to delete"
        )
    await record_event(
        session,
        action=AuditAction.api_token_revoked,
        actor_id=user.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
