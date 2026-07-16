from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from app.api.deps import AdminUser, Impersonator, SessionDep, get_request_token
from app.core.audit import record_event
from app.core.households import add_to_default_household
from app.core.rate_limit import client_ip
from app.core.security import (
    ADMIN_COOKIE_NAME,
    TOKEN_TTL,
    generate_token,
    hash_password,
    hash_token,
    set_auth_cookie,
)
from app.models import AuditAction, AuthToken, User
from app.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter()


async def _get_user_or_404(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _ensure_email_free(
    session: SessionDep, email: str, exclude_id: int | None = None
) -> None:
    query = select(User.id).where(User.email == email)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    if (await session.execute(query)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )


async def _revoke_tokens(session: SessionDep, user_id: int) -> None:
    await session.execute(delete(AuthToken).where(AuthToken.user_id == user_id))


def _protected_self_ids(admin: User, impersonator: User | None) -> set[int]:
    """Ids that may never demote/deactivate themselves. During impersonation
    that means the impersonated session AND the real operator behind the parked
    admin cookie, so the self-guard can't be bypassed by proxy."""
    return {admin.id} if impersonator is None else {admin.id, impersonator.id}


@router.get("", response_model=list[UserRead])
async def list_users(_: AdminUser, session: SessionDep) -> list[User]:
    result = await session.execute(select(User).order_by(User.id))
    return list(result.scalars())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    await _ensure_email_free(session, payload.email)
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        is_admin=payload.is_admin,
    )
    session.add(user)
    await session.flush()
    await add_to_default_household(session, user.id)
    await record_event(
        session,
        action=AuditAction.user_created,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> User:
    user = await _get_user_or_404(session, user_id)

    demoting = payload.is_admin is False
    deactivating = payload.is_active is False
    if user.id in _protected_self_ids(admin, impersonator) and (demoting or deactivating):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot demote or deactivate yourself",
        )

    # Record the fields that actually changed (never the values, so a password
    # reset is audited without leaking the password).
    changed: list[str] = []
    if payload.email is not None and payload.email != user.email:
        await _ensure_email_free(session, payload.email, exclude_id=user.id)
        user.email = payload.email
        changed.append("email")
    if payload.name is not None and payload.name != user.name:
        user.name = payload.name
        changed.append("name")
    if payload.is_admin is not None and payload.is_admin != user.is_admin:
        user.is_admin = payload.is_admin
        changed.append("is_admin")
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed.append("is_active")
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changed.append("password")

    # Force re-login when credentials or access change
    if payload.password is not None or deactivating:
        await _revoke_tokens(session, user.id)

    await record_event(
        session,
        action=AuditAction.user_updated,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
        detail=",".join(changed) or None,
    )
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/{user_id}/impersonate", response_model=UserRead)
async def impersonate_user(
    user_id: int,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
    response: Response,
) -> User:
    user = await _get_user_or_404(session, user_id)
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You are already this user"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot log in as an inactive user"
        )

    current = get_request_token(request)
    parked_admin = request.cookies.get(ADMIN_COOKIE_NAME)

    token = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + TOKEN_TTL,
        )
    )
    # Nested impersonation: the outermost admin stays parked in the admin cookie,
    # so the current (intermediate) session is about to lose its only cookie
    # reference. Revoke it rather than leave it valid for the full TTL (L2).
    if parked_admin and current and current != parked_admin:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash == hash_token(current)))
    # impersonator is set only for a nested impersonation; it records the
    # outermost operator so the chain traces back to a real admin.
    await record_event(
        session,
        action=AuditAction.impersonate_start,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()

    # Keep the outermost admin session for the return trip (don't overwrite it
    # when an impersonated admin impersonates someone else)
    if not parked_admin and current:
        set_auth_cookie(response, current, ADMIN_COOKIE_NAME)
    set_auth_cookie(response, token)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: int,
    admin: AdminUser,
    impersonator: Impersonator,
    session: SessionDep,
    request: Request,
) -> None:
    user = await _get_user_or_404(session, user_id)
    if user.id in _protected_self_ids(admin, impersonator):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate yourself"
        )
    user.is_active = False
    await _revoke_tokens(session, user.id)
    await record_event(
        session,
        action=AuditAction.user_deactivated,
        actor_id=admin.id,
        target_id=user.id,
        impersonator_id=impersonator.id if impersonator else None,
        ip=client_ip(request),
    )
    await session.commit()
