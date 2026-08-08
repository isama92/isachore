from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

import fakeredis.aioredis
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.v1 import auth as auth_module
from app.core import oidc as oidc_core
from app.core import security
from app.core.assignment import initial_assignee
from app.core.chores import RecurrenceRule, first_occurrence
from app.core.config import settings
from app.core.households import add_member, household_zone
from app.core.security import generate_token, hash_token
from app.db.base import Base
from app.db.redis import get_redis
from app.db.session import get_session
from app.main import app
from app.models import (
    AssignmentType,
    AuthToken,
    Chore,
    ChoreOccurrence,
    Household,
    HouseholdRole,
    OccurrenceStatus,
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
    # The real SPA sends X-CSRF-Token on every request (see frontend api wrapper);
    # mirror that so CsrfProtectMiddleware accepts mutations. Tests for the CSRF
    # check itself pop this header to assert the 403.
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-CSRF-Token": "1"}
    ) as ac:
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
    send_confirmation_email code runs and every path (admin_users, admin_settings,
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


@pytest.fixture(autouse=True)
def _reset_app_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic default: no encryption key, so crypto (and therefore 2FA) fails
    closed regardless of the container's env (compose/.env may set APP_KEY).
    Tests that need working encryption opt in via the `totp` fixture, which runs
    after this autouse one and sets a real key."""
    monkeypatch.setattr(settings, "app_key", None)


@pytest.fixture
def totp(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure a throwaway APP_KEY so 2FA setup/verify work. Returns the key
    (rarely needed; the plaintext TOTP secret comes from the /setup response or
    the direct-enrolment helper)."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "app_key", key)
    return key


@pytest.fixture(autouse=True)
def _reset_oidc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic default: no single sign-on provider, whatever the container's env says.

    Necessary rather than tidy. The suite runs inside the dev container with
    `env_file: .env`, so uncommenting the OIDC group in .env.example.dev to try the flow
    by hand would otherwise turn the sign-in button on for every test and make
    POST /auth/login 403 under OIDC_ONLY. Tests that want a provider opt in via the
    `oidc` fixture, which runs after this one.

    The cache clear is the other half: core/oidc.py memoises discovery documents and key
    sets per issuer, and a document cached by one test must not be served to the next.
    """
    monkeypatch.setattr(settings, "oidc_issuer", None)
    monkeypatch.setattr(settings, "oidc_client_id", None)
    monkeypatch.setattr(settings, "oidc_client_secret", None)
    monkeypatch.setattr(settings, "oidc_provider_name", "SSO")
    monkeypatch.setattr(settings, "oidc_scopes", "openid email profile")
    monkeypatch.setattr(settings, "oidc_only", False)
    oidc_core.reset_caches()


@pytest.fixture
def oidc(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure a single sign-on provider. Returns the issuer.

    https, so a case that also pins a non-dev environment cannot trip the startup check's
    plaintext-issuer refusal. (The startup-check tests themselves build their own config,
    since they assert on `check_startup_config()` directly rather than through an endpoint.)

    Nothing here reaches the network: the endpoint tests stub oidc_core.begin /
    oidc_core.complete, the verification tests stub the key set, and the provider-facing
    tests stub the httpx client.
    """
    issuer = "https://idp.example.com/application/o/isachore"
    monkeypatch.setattr(settings, "oidc_issuer", issuer)
    monkeypatch.setattr(settings, "oidc_client_id", "isachore-client")
    monkeypatch.setattr(settings, "oidc_client_secret", "shh-client-secret")
    monkeypatch.setattr(settings, "oidc_provider_name", "Authentik")
    return issuer


@pytest.fixture
def make_household(db_session: AsyncSession) -> Callable[..., Awaitable[Household]]:
    counter = {"n": 0}

    async def _make(
        *,
        name: str = "Test Household",
        members: list[User] | None = None,
        admin: User | None = None,
        deleted_at: datetime | None = None,
        roles: dict[int, HouseholdRole] | None = None,
        timezone: str = "UTC",
    ) -> Household:
        # UTC by default, matching the column's server_default. Load-bearing in the same way
        # the organiser default below is: every due assertion in the suite predates household
        # zones and was written against a UTC day, so any other default would silently re-date
        # several hundred fixtures. Tests about timezones pass one explicitly.
        # Every member is an organiser unless `roles` (keyed by user id) says otherwise.
        # That default is deliberate and load-bearing: before roles existed, membership
        # granted everything, so it is what keeps the chores / tags / stats / history
        # suites testing the behaviour they were written for instead of quietly becoming
        # several hundred assertions about 403s. Tests about a role pass `roles`.
        #
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
        household = Household(
            name=name, admin_id=admin_id, deleted_at=deleted_at, timezone=timezone
        )
        db_session.add(household)
        await db_session.flush()  # assigns household.id, which add_member needs
        # Not `household.members.extend(...)`: the relationship writes the two foreign keys
        # only, so every row would land on the role column's helper server_default and the
        # `roles` argument above would silently do nothing.
        for member in members or []:
            await add_member(
                db_session,
                household.id,
                member.id,
                (roles or {}).get(member.id, HouseholdRole.organiser),
            )
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
        turn_length: int = 1,
        repeat_interval: int = 1,
        weekdays: list[int] | None = None,
        assignees: list[User] | None = None,
        tags: list[Tag] | None = None,
        current_assignee: User | None = None,
        with_occurrence: bool = True,
    ) -> Chore:
        pool = assignees or []
        # The slot the first occurrence opens at. An unscheduled chore stores NO start date
        # (the schema layer forces it to None, so a fixture holding one would let a bug
        # through), but the date still places its occurrence chain, exactly as the seeder's
        # `start_days_ago` does: that is how a test says "last done a fortnight ago".
        slot_from = start_date or date(2026, 7, 16)
        chore = Chore(
            household_id=household.id,
            title=title,
            description=description,
            start_date=None if repeats == RepeatPeriod.manual else slot_from,
            repeats=repeats,
            assignment_type=assignment_type,
            turn_length=turn_length,
            repeat_interval=repeat_interval,
            weekdays=weekdays,
        )
        if pool:
            chore.assignees.extend(pool)
        if tags:
            chore.tags.extend(tags)
        db_session.add(chore)
        await db_session.flush()
        # Mirror the create endpoint: give the chore its first open occurrence unless a
        # test wants to build a custom occurrence history itself (with_occurrence=False).
        if with_occurrence:
            current = current_assignee or initial_assignee(assignment_type, pool)
            # Build the first slot through the real helper, rule and all: a pinned-weekday
            # fixture placed at plain midnight-of-start-date would start off the grid and
            # mask exactly the bugs the weekday tests exist to catch.
            rule = RecurrenceRule.of(repeats, repeat_interval, weekdays)
            db_session.add(
                ChoreOccurrence(
                    chore_id=chore.id,
                    # Anchored in the household's zone, like the create endpoint: a fixture
                    # placed at midnight UTC in a non-UTC household would sit off the grid the
                    # endpoints compute against, and the timezone tests would pass by accident.
                    scheduled_for=first_occurrence(
                        slot_from, rule, household_zone(household.timezone)
                    ),
                    assignee_id=current.id if current is not None else None,
                    status=OccurrenceStatus.open,
                )
            )
        await db_session.commit()
        await db_session.refresh(chore, attribute_names=["assignees", "tags"])
        return chore

    return _make


@pytest.fixture
def make_occurrence(db_session: AsyncSession) -> Callable[..., Awaitable[ChoreOccurrence]]:
    async def _make(
        *,
        chore: Chore,
        scheduled_for: datetime,
        assignee: User | None = None,
        status: OccurrenceStatus = OccurrenceStatus.open,
        completed_by: User | None = None,
        completed_at: datetime | None = None,
        completed_timezone: str | None = None,
        title: str | None = None,
        skipped: bool = False,
    ) -> ChoreOccurrence:
        # A done occurrence snapshots its title; an open one reads the live chore title.
        # `skipped=True` builds the other kind of closure, for tests that need one in place
        # rather than going through the endpoint (history, stats, "last done").
        #
        # **Build a chore's occurrences in chain order: done rows first, the open one last.**
        # Production cannot do otherwise - a done row is only ever produced by flipping the
        # single open row, so the open row always holds the chain's highest id - and
        # `undo_completion` relies on that, deciding which closure is the latest by `max(id)`.
        # Insert an open row and then a done one and the state is unreachable by any real code
        # path, so a test built on it asserts against a chore that could not exist.
        occurrence = ChoreOccurrence(
            chore_id=chore.id,
            scheduled_for=scheduled_for,
            assignee_id=assignee.id if assignee is not None else None,
            status=status,
            title=(title if title is not None else chore.title)
            if status == OccurrenceStatus.done
            else None,
            completed_by_user_id=completed_by.id if completed_by is not None else None,
            completed_at=completed_at,
            # NULL unless a test says otherwise, which is the same shape as a closure written
            # before the column existed: the readers fall back to the household's current zone,
            # so every pre-existing history assertion keeps meaning what it did.
            completed_timezone=completed_timezone,
            skipped=skipped,
        )
        db_session.add(occurrence)
        await db_session.commit()
        await db_session.refresh(occurrence)
        return occurrence

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
