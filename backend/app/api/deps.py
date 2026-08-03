from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.households import member_household_ids
from app.core.security import ADMIN_COOKIE_NAME, COOKIE_NAME, hash_token
from app.db.redis import get_redis
from app.db.session import get_session
from app.models import AuthToken, Household, HouseholdRole, User, UserStatus

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)


def get_request_token(request: Request) -> str | None:
    """Raw auth token from the session cookie or an Authorization: Bearer header."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token
    authorization = request.headers.get("Authorization", "")
    scheme, _, param = authorization.partition(" ")
    if scheme.lower() == "bearer" and param:
        return param
    return None


async def get_user_by_token(session: AsyncSession, token: str) -> User | None:
    """Resolve a raw token to its active user, or None if invalid/expired/inactive."""
    result = await session.execute(
        select(AuthToken)
        .options(joinedload(AuthToken.user))
        .where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.expires_at > datetime.now(UTC),
        )
    )
    auth_token = result.scalar_one_or_none()
    if auth_token is None or auth_token.user.status != UserStatus.active:
        return None
    return auth_token.user


async def get_current_user(request: Request, session: SessionDep) -> User:
    token = get_request_token(request)
    user = await get_user_by_token(session, token) if token else None
    if user is None:
        raise _credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def get_impersonator(request: Request, session: SessionDep) -> User | None:
    """The real admin behind an impersonation session (from the parked admin
    cookie), or None when not impersonating."""
    admin_token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not admin_token:
        return None
    admin = await get_user_by_token(session, admin_token)
    return admin if admin is not None and admin.is_admin else None


Impersonator = Annotated[User | None, Depends(get_impersonator)]


async def get_current_household(
    user: CurrentUser, session: SessionDep, min_role: HouseholdRole | None = None
) -> Household:
    """The current user's active household, lowest id first, as a fallback for
    callers that take no explicit household_id.

    Being a member of none is a normal state (nothing provisions a household), so
    the 404 below is a routine answer rather than an anomaly, and callers with a UI
    are expected to check first. Excludes soft-deleted households so the fallback
    stays consistent with get_member_household and the /households list (which both
    hide deleted ones). `min_role` narrows it to the households where the caller's role
    grants that much, so the fallback cannot hand back one they may not act in.

    Call this directly, never through `Depends`: `min_role` is a plain scalar with a default,
    so FastAPI would resolve it as a query parameter and publish a permission helper's floor
    as client input. It only ever narrows, so that would fail closed rather than escalate, but
    there is no reason to offer it. There used to be a `CurrentHousehold` annotated alias here
    for exactly that; it had no callers and was removed."""
    result = await session.execute(
        select(Household)
        .where(Household.id.in_(member_household_ids(user.id, min_role)))
        .order_by(Household.id)
        .limit(1)
    )
    household = result.scalar_one_or_none()
    if household is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "You are not a member of any household"
                if min_role is None
                else f"You are not a household {min_role} anywhere"
            ),
        )
    return household
