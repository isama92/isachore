from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.v1 import auth as auth_module
from app.core import security
from app.core.config import settings
from app.core.security import generate_token, hash_token
from app.db.base import Base
from app.db.redis import get_redis
from app.db.session import get_session
from app.main import app
from app.models import (
    AssignmentType,
    AuthToken,
    Chore,
    CompletedChore,
    Household,
    RepeatPeriod,
    Tag,
    User,
    UserStatus,
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
async def fake_redis() -> AsyncIterator[Redis]:
    # In-process Redis so tests need no real server and stay isolated (a fresh
    # instance per test, flushed on teardown).
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield redis
    finally:
        await redis.flushall()
        await redis.aclose()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    # The test client talks HTTP (http://testserver) and httpx won't send Secure
    # cookies over HTTP, so pin the non-secure path regardless of the ambient
    # COOKIES_SECURE (default is now fail-closed True).
    monkeypatch.setattr(settings, "cookies_secure", False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _override_get_redis() -> Redis:
        return fake_redis

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_redis] = _override_get_redis
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    async def _make(
        *,
        email: str = "member@example.com",
        first_name: str = "Test",
        last_name: str = "Member",
        password: str = "password12345",
        is_admin: bool = False,
        status: UserStatus = UserStatus.active,
        confirmed_at: datetime | None = None,
    ) -> User:
        # An active user has, by definition, completed setup, so default
        # confirmed_at unless a test wants the "active but unconfirmed" edge.
        if confirmed_at is None and status == UserStatus.active:
            confirmed_at = datetime.now(UTC)
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password_hash=security.hash_password(password),
            is_admin=is_admin,
            status=status,
            confirmed_at=confirmed_at,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make


@pytest.fixture(autouse=True)
def _reset_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic default: SMTP unconfigured regardless of the container's env
    (compose sets SMTP_* to point at mailpit in dev). Tests that need a
    configured relay opt in via the `smtp` fixture, which runs after this
    autouse one and re-sets the values."""
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "smtp_from", None)
    # Pin the port too: the dev compose env sets SMTP_PORT=1025, which would
    # otherwise leak into the container's test run and make assertions flaky.
    monkeypatch.setattr(settings, "smtp_port", 587)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> list:
    """Configure SMTP and capture outgoing mail without hitting the network.

    Patches the single chokepoint (aiosmtplib.send) so the real send_email /
    send_confirmation_email code runs and every path (users, server_settings,
    resend) is captured. Returns the list of sent EmailMessage objects.
    """
    monkeypatch.setattr(settings, "smtp_host", "mailpit")
    monkeypatch.setattr(settings, "smtp_from", "isachore <no-reply@example.com>")
    sent: list = []

    async def _fake_send(message, **kwargs):
        sent.append(message)
        return {}, "OK"

    monkeypatch.setattr("aiosmtplib.send", _fake_send)
    return sent


@pytest.fixture
def make_household(db_session: AsyncSession) -> Callable[..., Awaitable[Household]]:
    counter = {"n": 0}

    async def _make(
        *,
        name: str = "Test Household",
        members: list[User] | None = None,
        admin: User | None = None,
        deleted_at: datetime | None = None,
    ) -> Household:
        # admin_id is NOT NULL. Default the owner to the given admin, else the
        # first member; with neither, mint a throwaway owner (not added as a
        # member) so member-less fixtures keep their member_count of 0.
        if admin is not None:
            admin_id = admin.id
        elif members:
            admin_id = members[0].id
        else:
            counter["n"] += 1
            owner = User(
                email=f"owner{counter['n']}@example.com",
                first_name="Owner",
                last_name="User",
                password_hash=security.hash_password("password12345"),
                status=UserStatus.active,
                confirmed_at=datetime.now(UTC),
            )
            db_session.add(owner)
            await db_session.flush()
            admin_id = owner.id
        household = Household(name=name, admin_id=admin_id, deleted_at=deleted_at)
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
        last_completed_at: datetime | None = None,
    ) -> Chore:
        chore = Chore(
            household_id=household.id,
            title=title,
            description=description,
            start_date=start_date or date(2026, 7, 16),
            repeats=repeats,
            assignment_type=assignment_type,
            last_completed_at=last_completed_at,
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
def make_completion(db_session: AsyncSession) -> Callable[..., Awaitable[CompletedChore]]:
    async def _make(
        *,
        chore: Chore,
        scheduled_for: datetime,
        completed_by: User | None = None,
        created_at: datetime | None = None,
        title: str | None = None,
    ) -> CompletedChore:
        completion = CompletedChore(
            chore_id=chore.id,
            title=title if title is not None else chore.title,
            scheduled_for=scheduled_for,
            completed_by_user_id=completed_by.id if completed_by is not None else None,
        )
        # Let tests pin created_at (e.g. "completed yesterday") instead of now().
        if created_at is not None:
            completion.created_at = created_at
        db_session.add(completion)
        await db_session.commit()
        await db_session.refresh(completion)
        return completion

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
