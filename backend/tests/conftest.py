from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.v1 import auth as auth_module
from app.core import security
from app.core.config import settings
from app.core.security import generate_token, hash_token
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models import (
    AssignmentType,
    AuthToken,
    Chore,
    Household,
    RepeatPeriod,
    Tag,
    User,
)

# A throwaway database in the same Postgres instance as dev, resolved from the
# configured URL so it works both in-container (host "db") and host-side.
TEST_DB_URL = make_url(settings.database_url).set(database="isachore_test")


@pytest.fixture(scope="session", autouse=True)
def _fast_argon2() -> None:
    """Swap Argon2 for minimal-cost params so hashing doesn't dominate runtime.

    The real code path (pwdlib/argon2) is still exercised, just cheaply. The
    hasher is read at call time by hash_password/verify_password, but auth.py
    binds DUMMY_PASSWORD_HASH by value at import, so patch that too.
    """
    cheap = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))
    security._password_hash = cheap
    auth_module.DUMMY_PASSWORD_HASH = cheap.hash("dummy-password-for-timing")


@pytest_asyncio.fixture(scope="session")
async def _create_test_db() -> None:
    admin_engine = create_async_engine(
        make_url(settings.database_url), isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TEST_DB_URL.database},
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB_URL.database}"'))
    await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_engine(_create_test_db: None) -> AsyncIterator:
    engine = create_async_engine(TEST_DB_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncIterator[AsyncSession]:
    # Outer transaction is never committed; the session commits inside it via
    # SAVEPOINTs (join_transaction_mode), so endpoint commits don't leak and
    # teardown rolls everything back.
    conn = await test_engine.connect()
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    # The test client talks HTTP (http://testserver) and httpx won't send Secure
    # cookies over HTTP, so pin the non-secure path regardless of the ambient
    # COOKIES_SECURE (default is now fail-closed True).
    monkeypatch.setattr(settings, "cookies_secure", False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    async def _make(
        *,
        email: str = "member@example.com",
        name: str = "Test Member",
        password: str = "password12345",
        is_admin: bool = False,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            name=name,
            password_hash=security.hash_password(password),
            is_admin=is_admin,
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make


@pytest.fixture
def make_household(db_session: AsyncSession) -> Callable[..., Awaitable[Household]]:
    async def _make(
        *,
        name: str = "Test Household",
        members: list[User] | None = None,
    ) -> Household:
        household = Household(name=name)
        if members:
            household.members.extend(members)
        db_session.add(household)
        await db_session.commit()
        await db_session.refresh(household)
        return household

    return _make


@pytest.fixture
def make_tag(db_session: AsyncSession) -> Callable[..., Awaitable[Tag]]:
    async def _make(
        *,
        household: Household,
        name: str = "cleaning",
        color: str = "#0d9488",
    ) -> Tag:
        tag = Tag(household_id=household.id, name=name, color=color)
        db_session.add(tag)
        await db_session.commit()
        await db_session.refresh(tag)
        return tag

    return _make


@pytest.fixture
def make_chore(db_session: AsyncSession) -> Callable[..., Awaitable[Chore]]:
    async def _make(
        *,
        household: Household,
        title: str = "Clean the bathroom",
        description: str | None = None,
        start_date: date | None = None,
        repeats: RepeatPeriod = RepeatPeriod.weekly,
        assignment_type: AssignmentType = AssignmentType.manual,
        assignees: list[User] | None = None,
        tags: list[Tag] | None = None,
    ) -> Chore:
        chore = Chore(
            household_id=household.id,
            title=title,
            description=description,
            start_date=start_date or date(2026, 7, 16),
            repeats=repeats,
            assignment_type=assignment_type,
        )
        if assignees:
            chore.assignees.extend(assignees)
        if tags:
            chore.tags.extend(tags)
        db_session.add(chore)
        await db_session.commit()
        await db_session.refresh(chore, attribute_names=["assignees", "tags"])
        return chore

    return _make


@pytest.fixture
def auth_client(
    client: AsyncClient, db_session: AsyncSession
) -> Callable[[User], Awaitable[AsyncClient]]:
    async def _auth(user: User) -> AsyncClient:
        raw = generate_token()
        db_session.add(
            AuthToken(
                token_hash=hash_token(raw),
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db_session.commit()
        client.cookies.set("isachore_token", raw)
        return client

    return _auth
