from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, SessionDep, get_request_token, get_user_by_token
from app.core.security import (
    ADMIN_COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    TOKEN_TTL,
    clear_auth_cookie,
    generate_token,
    hash_token,
    set_auth_cookie,
    verify_password,
)
from app.models import AuthToken, User
from app.schemas import LoginRequest, MeRead, UserRead

router = APIRouter()


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

    set_auth_cookie(response, token)
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, session: SessionDep, response: Response) -> None:
    # Ends both the current session and, when impersonating, the admin one
    hashes = []
    if token := get_request_token(request):
        hashes.append(hash_token(token))
    if admin_token := request.cookies.get(ADMIN_COOKIE_NAME):
        hashes.append(hash_token(admin_token))
    if hashes:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash.in_(hashes)))
        await session.commit()
    clear_auth_cookie(response)
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)


@router.get("/me", response_model=MeRead)
async def me(request: Request, user: CurrentUser, session: SessionDep) -> MeRead:
    impersonating = False
    if admin_token := request.cookies.get(ADMIN_COOKIE_NAME):
        admin = await get_user_by_token(session, admin_token)
        impersonating = admin is not None and admin.is_admin
    return MeRead.model_validate(user).model_copy(update={"impersonating": impersonating})


@router.post("/stop-impersonating", response_model=UserRead)
async def stop_impersonating(request: Request, session: SessionDep, response: Response) -> User:
    admin_token = request.cookies.get(ADMIN_COOKIE_NAME)
    admin = await get_user_by_token(session, admin_token) if admin_token else None
    if admin_token is None or admin is None or not admin.is_admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No impersonation in progress"
        )

    # Drop the impersonated session and restore the admin one
    current = get_request_token(request)
    if current and current != admin_token:
        await session.execute(delete(AuthToken).where(AuthToken.token_hash == hash_token(current)))
        await session.commit()

    set_auth_cookie(response, admin_token)
    clear_auth_cookie(response, ADMIN_COOKIE_NAME)
    return admin
