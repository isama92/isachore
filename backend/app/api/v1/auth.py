from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, SessionDep, get_request_token
from app.core.config import settings
from app.core.security import (
    COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    TOKEN_TTL,
    generate_token,
    hash_token,
    verify_password,
)
from app.models import AuthToken, User
from app.schemas import LoginRequest, UserRead

router = APIRouter()


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(TOKEN_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.environment != "dev",
    )


@router.post("/login", response_model=UserRead)
async def login(payload: LoginRequest, session: SessionDep, response: Response) -> User:
    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    password_ok = verify_password(
        payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok or not user.is_active:
        # One message for every failure mode so emails can't be enumerated
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    token = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + TOKEN_TTL,
        )
    )
    await session.commit()

    _set_auth_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep, response: Response) -> None:
    token = get_request_token(request)
    if token:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash == hash_token(token)))
        await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user
