from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.security import COOKIE_NAME, hash_token
from app.db.session import get_session
from app.models import AuthToken, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]

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


async def get_current_user(request: Request, session: SessionDep) -> User:
    token = get_request_token(request)
    if not token:
        raise _credentials_exc

    result = await session.execute(
        select(AuthToken)
        .options(joinedload(AuthToken.user))
        .where(
            AuthToken.token_hash == hash_token(token),
            AuthToken.expires_at > datetime.now(UTC),
        )
    )
    auth_token = result.scalar_one_or_none()
    if auth_token is None or not auth_token.user.is_active:
        raise _credentials_exc
    return auth_token.user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
