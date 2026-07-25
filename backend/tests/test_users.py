from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.models import AuthToken, ConfirmationToken, Household, User, UserStatus, household_members
from app.models.app_settings import APP_SETTINGS_ID, AppSettings

Login = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]


async def _token_count(session: AsyncSession, user_id: int) -> int:
    query = select(func.count()).select_from(AuthToken).where(AuthToken.user_id == user_id)
    return await session.scalar(query) or 0


async def _issue_token(session: AsyncSession, user: User) -> str:
    raw = generate_token()
    session.add(
        AuthToken(
            token_hash=hash_token(raw),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await session.commit()
    return raw


# --- list ---------------------------------------------------------------


async def test_list_users_as_admin(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users")

    assert resp.status_code == 200
    body = resp.json()
    # Enveloped page: no status filter by default, so both users come back.
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert {u["email"] for u in body["items"]} == {"admin@example.com", "member@example.com"}


async def test_list_users_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin only"


async def test_list_users_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


async def test_list_users_pagination(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    for i in range(4):
        await make_user(email=f"user{i}@example.com")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users?page=1&page_size=2&sort_by=id&sort_dir=asc")
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    first_ids = [u["id"] for u in body["items"]]

    resp = await client.get("/api/v1/users?page=2&page_size=2&sort_by=id&sort_dir=asc")
    body = resp.json()
    assert len(body["items"]) == 2
    second_ids = [u["id"] for u in body["items"]]
    # Distinct rows, ascending across pages
    assert set(first_ids).isdisjoint(second_ids)
    assert max(first_ids) < min(second_ids)

    resp = await client.get("/api/v1/users?page=3&page_size=2&sort_by=id&sort_dir=asc")
    assert len(resp.json()["items"]) == 1  # remainder


async def test_list_users_sort_by_name_and_email(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="m@example.com", is_admin=True, first_name="Mid", last_name="Mid")
    await make_user(email="a@example.com", first_name="Anna", last_name="Aaa")
    await make_user(email="z@example.com", first_name="Zoe", last_name="Zzz")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users?sort_by=name&sort_dir=asc")
    assert [u["first_name"] for u in resp.json()["items"]] == ["Anna", "Mid", "Zoe"]

    resp = await client.get("/api/v1/users?sort_by=email&sort_dir=desc")
    assert [u["email"] for u in resp.json()["items"]] == [
        "z@example.com",
        "m@example.com",
        "a@example.com",
    ]


async def test_list_users_sort_by_created_at(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    # func.now() is the transaction timestamp, so users made in one test share a
    # created_at; assign distinct values to exercise the ordering.
    admin = await make_user(email="admin@example.com", is_admin=True)
    old = await make_user(email="old@example.com")
    new = await make_user(email="new@example.com")
    old.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    admin.created_at = datetime(2022, 1, 1, tzinfo=UTC)
    new.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    await db_session.commit()
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users?sort_by=created_at&sort_dir=desc")
    assert [u["email"] for u in resp.json()["items"]] == [
        "new@example.com",
        "admin@example.com",
        "old@example.com",
    ]

    resp = await client.get("/api/v1/users?sort_by=created_at&sort_dir=asc")
    assert [u["email"] for u in resp.json()["items"]] == [
        "old@example.com",
        "admin@example.com",
        "new@example.com",
    ]


async def test_list_users_filter_by_name_searches_both_fields(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(
        email="admin@example.com", is_admin=True, first_name="Zed", last_name="Zulu"
    )
    await make_user(email="alice@example.com", first_name="Alice", last_name="Smith")
    await make_user(email="bob@example.com", first_name="Bob", last_name="Alicorn")
    client = await auth_client(admin)

    # "ali" matches Alice (first name) and Alicorn (last name), case-insensitively
    resp = await client.get("/api/v1/users?name=ALI")
    assert {u["email"] for u in resp.json()["items"]} == {
        "alice@example.com",
        "bob@example.com",
    }


async def test_list_users_filter_by_email(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="alice@example.com")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users?email=ALICE")  # case-insensitive substring
    assert {u["email"] for u in resp.json()["items"]} == {"alice@example.com"}


async def test_list_users_name_filter_escapes_wildcards(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(
        email="admin@example.com", is_admin=True, first_name="Real", last_name="Name"
    )
    await make_user(email="pct@example.com", first_name="50%", last_name="Off")
    client = await auth_client(admin)

    # A literal '%' must not act as a wildcard (which would match everyone).
    resp = await client.get("/api/v1/users", params={"name": "%"})
    assert {u["email"] for u in resp.json()["items"]} == {"pct@example.com"}


async def test_list_users_filter_by_status(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)  # active
    await make_user(email="waiting@example.com", status=UserStatus.waiting_confirmation)
    await make_user(email="disabled@example.com", status=UserStatus.disabled)
    client = await auth_client(admin)

    assert (await client.get("/api/v1/users")).json()["total"] == 3  # no filter

    resp = await client.get("/api/v1/users?status=active")
    assert {u["email"] for u in resp.json()["items"]} == {"admin@example.com"}

    resp = await client.get("/api/v1/users?status=waiting_confirmation")
    assert {u["email"] for u in resp.json()["items"]} == {"waiting@example.com"}

    resp = await client.get("/api/v1/users?status=disabled")
    assert {u["email"] for u in resp.json()["items"]} == {"disabled@example.com"}


async def test_list_users_filter_by_role(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users?role=admins")
    assert {u["email"] for u in resp.json()["items"]} == {"admin@example.com"}

    resp = await client.get("/api/v1/users?role=members")
    assert {u["email"] for u in resp.json()["items"]} == {"member@example.com"}


async def test_list_users_invalid_params_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    for query in (
        "sort_by=bogus",
        "sort_dir=sideways",
        "page_size=101",
        "page=0",
        "status=bogus",
        "role=superuser",
    ):
        resp = await client.get(f"/api/v1/users?{query}")
        assert resp.status_code == 422, query


# --- get one ------------------------------------------------------------


async def test_get_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    target = await make_user(email="member@example.com", first_name="Jo", last_name="Ng")
    client = await auth_client(admin)

    resp = await client.get(f"/api/v1/users/{target.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == target.id
    assert body["email"] == "member@example.com"
    assert body["first_name"] == "Jo"
    assert body["is_admin"] is False


async def test_get_user_not_found(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.get("/api/v1/users/999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


async def test_get_user_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    client = await auth_client(member)

    resp = await client.get(f"/api/v1/users/{other.id}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin only"


async def test_get_user_unauthenticated(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/1")
    assert resp.status_code == 401


# --- create -------------------------------------------------------------


async def test_create_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "newbie@example.com",
            "first_name": "New",
            "last_name": "Member",
            "password": "password12345",
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "newbie@example.com"
    assert body["first_name"] == "New"
    assert body["last_name"] == "Member"
    assert body["is_admin"] is False
    assert body["status"] == "active"
    assert body["confirmed_at"] is not None
    assert "password_hash" not in body

    # password stored hashed -> the new credentials actually work
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "newbie@example.com", "password": "password12345"},
    )
    assert login.status_code == 200


async def _household_ids(session: AsyncSession, user_id: int) -> list[int]:
    result = await session.execute(
        select(household_members.c.household_id).where(household_members.c.user_id == user_id)
    )
    return list(result.scalars().all())


async def test_create_user_gives_them_their_own_household(
    make_user: Login,
    auth_client: AuthClient,
    db_session: AsyncSession,
    make_household: Callable[..., Awaitable[Household]],
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    admin_household = await make_household(name="Admin's place", members=[admin])
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "newbie@example.com",
            "first_name": "New",
            "last_name": "Member",
            "password": "password12345",
        },
    )

    assert resp.status_code == 201
    new_id = resp.json()["id"]
    memberships = await _household_ids(db_session, new_id)
    assert len(memberships) == 1
    # Emphatically NOT the admin's household: the previous behaviour joined the
    # lowest-id one, which would expose a stranger's chores to every new account.
    assert memberships[0] != admin_household.id
    household = await db_session.get(Household, memberships[0])
    assert household is not None
    assert household.admin_id == new_id
    assert household.name == "New's place"
    # The admin's own household gained nobody.
    assert await _household_ids(db_session, admin.id) == [admin_household.id]


async def test_create_user_waiting_confirmation_still_gets_a_household(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    # The household is created with the account, not at confirmation time, so a
    # user who has not clicked the link yet still owns one.
    await _enable_confirmation(db_session)
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "newbie@example.com", "first_name": "New", "last_name": "Member"},
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "waiting_confirmation"
    memberships = await _household_ids(db_session, resp.json()["id"])
    assert len(memberships) == 1


async def test_create_user_with_a_very_long_first_name(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    # The generated household name appends "'s place" to the first name, and
    # households.name is varchar(255) while first_name is accepted up to 255. An
    # unclipped name would overflow and turn this 201 into a 500, rolling back the
    # account too.
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "long@example.com",
            "first_name": "N" * 255,
            "last_name": "Member",
            "password": "password12345",
        },
    )

    assert resp.status_code == 201
    memberships = await _household_ids(db_session, resp.json()["id"])
    household = await db_session.get(Household, memberships[0])
    assert household is not None
    assert len(household.name) <= 255
    assert household.name.endswith("'s place")


async def test_create_user_duplicate_email(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="taken@example.com")
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "taken@example.com",
            "first_name": "Dup",
            "last_name": "Licate",
            "password": "password12345",
        },
    )
    assert resp.status_code == 409


async def test_create_user_normalises_email_case(make_user: Login, auth_client: AuthClient) -> None:
    # Email is stored lower-cased so casing can't create a duplicate account (L3)
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "Mixed@Example.com",
            "first_name": "Mixed",
            "last_name": "Case",
            "password": "password12345",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "mixed@example.com"


async def test_create_user_duplicate_email_case_insensitive(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    await make_user(email="taken@example.com")
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "Taken@Example.com",
            "first_name": "Dup",
            "last_name": "Licate",
            "password": "password12345",
        },
    )
    assert resp.status_code == 409


async def test_create_user_invalid_payload(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "not-an-email", "first_name": "", "last_name": "", "password": "short"},
    )
    assert resp.status_code == 422


async def test_create_user_blank_first_name_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    # Isolates the name min_length: everything else is valid, only first_name is empty.
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "blank@example.com",
            "first_name": "",
            "last_name": "Person",
            "password": "password12345",
        },
    )
    assert resp.status_code == 422


async def test_create_user_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    client = await auth_client(member)
    resp = await client.post(
        "/api/v1/users",
        json={
            "email": "x@example.com",
            "first_name": "Ex",
            "last_name": "Ample",
            "password": "password12345",
        },
    )
    assert resp.status_code == 403


# --- update -------------------------------------------------------------


async def test_update_user_name_and_email(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", first_name="Old", last_name="Name")
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/users/{member.id}",
        json={"first_name": "New", "last_name": "Name", "email": "renamed@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "New"
    assert resp.json()["last_name"] == "Name"
    assert resp.json()["email"] == "renamed@example.com"


async def test_update_user_email_conflict(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"email": other.email})
    assert resp.status_code == 409


async def test_update_own_unchanged_email_allowed(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"email": "admin@example.com", "first_name": "Renamed", "last_name": "Admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Renamed"
    assert resp.json()["last_name"] == "Admin"


async def test_update_self_demote_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.patch(f"/api/v1/users/{admin.id}", json={"is_admin": False})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot demote or deactivate yourself"


async def test_update_self_deactivate_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.patch(f"/api/v1/users/{admin.id}", json={"status": "disabled"})
    assert resp.status_code == 400


async def test_update_password_revokes_tokens(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await _issue_token(db_session, member)
    assert await _token_count(db_session, member.id) == 1
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"password": "newpassword123"})

    assert resp.status_code == 200
    assert await _token_count(db_session, member.id) == 0


async def test_update_deactivate_revokes_tokens(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await _issue_token(db_session, member)
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"status": "disabled"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"
    assert await _token_count(db_session, member.id) == 0


async def test_update_missing_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.patch("/api/v1/users/999999", json={"first_name": "Nope"})
    assert resp.status_code == 404


# --- impersonation ------------------------------------------------------


async def test_impersonation_round_trip(client: AsyncClient, make_user: Login) -> None:
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    member = await make_user(email="member@example.com")

    # Drive the whole state machine through one client so the cookie jar carries
    # every Set-Cookie the way a browser would.
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )

    imp = await client.post(f"/api/v1/users/{member.id}/impersonate")
    assert imp.status_code == 200
    assert imp.json()["email"] == "member@example.com"

    me = await client.get("/api/v1/auth/me")
    assert me.json()["email"] == "member@example.com"
    assert me.json()["impersonating"] is True

    stop = await client.post("/api/v1/auth/stop-impersonating")
    assert stop.status_code == 200
    assert stop.json()["email"] == "admin@example.com"

    me_again = await client.get("/api/v1/auth/me")
    assert me_again.json()["email"] == "admin@example.com"
    assert me_again.json()["impersonating"] is False


async def test_impersonate_self_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.post(f"/api/v1/users/{admin.id}/impersonate")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "You are already this user"


async def test_impersonate_inactive_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", status=UserStatus.disabled)
    client = await auth_client(admin)
    resp = await client.post(f"/api/v1/users/{member.id}/impersonate")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot log in as an inactive user"


async def test_impersonate_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    target = await make_user(email="target@example.com")
    client = await auth_client(member)
    resp = await client.post(f"/api/v1/users/{target.id}/impersonate")
    assert resp.status_code == 403


async def test_nested_impersonation_revokes_intermediate_token(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    # A impersonates admin B, then (as B) impersonates member U. The outermost
    # admin (A) stays parked in the admin cookie, so B's session token would be
    # orphaned: it must be revoked, not left valid for the full TTL (L2).
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    bob = await make_user(email="bob@example.com", is_admin=True)
    member = await make_user(email="member@example.com")

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{bob.id}/impersonate")
    bob_token = client.cookies.get("isachore_token")
    assert bob_token is not None

    resp = await client.post(f"/api/v1/users/{member.id}/impersonate")
    assert resp.status_code == 200

    orphaned = await db_session.scalar(
        select(AuthToken.id).where(AuthToken.token_hash == hash_token(bob_token))
    )
    assert orphaned is None

    # The outermost admin session survives: the return trip lands back on A
    stop = await client.post("/api/v1/auth/stop-impersonating")
    assert stop.status_code == 200
    assert stop.json()["email"] == "admin@example.com"


# --- impersonation self-guard (H1) --------------------------------------
# The "cannot demote/deactivate yourself" guard must protect the real operator
# behind the parked admin cookie, not just the impersonated session identity.
# Otherwise an admin who impersonates a second admin could strip or deactivate
# their own real account by proxy.


async def test_impersonating_admin_cannot_demote_real_operator(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    # Acting as Eve, demoting the operator's own real account must be refused
    resp = await client.patch(f"/api/v1/users/{admin.id}", json={"is_admin": False})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot demote or deactivate yourself"
    await db_session.refresh(admin)
    assert admin.is_admin is True


async def test_impersonating_admin_cannot_deactivate_real_operator(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    resp = await client.delete(f"/api/v1/users/{admin.id}")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot deactivate yourself"
    await db_session.refresh(admin)
    assert admin.status == UserStatus.active


async def test_impersonating_admin_cannot_demote_current_session(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    # The impersonated session identity is still guarded (the "as well as the
    # current one" half of the fix)
    resp = await client.patch(f"/api/v1/users/{eve.id}", json={"is_admin": False})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot demote or deactivate yourself"
    await db_session.refresh(eve)
    assert eve.is_admin is True


async def test_impersonating_admin_can_demote_other_admin(
    client: AsyncClient, make_user: Login, db_session: AsyncSession
) -> None:
    await make_user(email="admin@example.com", password="password12345", is_admin=True)
    eve = await make_user(email="eve@example.com", is_admin=True)
    carol = await make_user(email="carol@example.com", is_admin=True)

    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password12345"},
    )
    await client.post(f"/api/v1/users/{eve.id}/impersonate")

    # A third admin who is neither the operator nor the impersonated session can
    # still be managed: the guard is scoped to the self-ids, not all admins
    resp = await client.patch(f"/api/v1/users/{carol.id}", json={"is_admin": False})

    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False
    await db_session.refresh(carol)
    assert carol.is_admin is False


# --- delete (soft) ------------------------------------------------------


async def test_delete_user_soft(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    await _issue_token(db_session, member)
    client = await auth_client(admin)

    resp = await client.delete(f"/api/v1/users/{member.id}")

    assert resp.status_code == 204
    assert await _token_count(db_session, member.id) == 0
    # Row still present, just disabled (soft delete)
    refreshed = await db_session.get(User, member.id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.status == UserStatus.disabled


async def test_delete_self_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.delete(f"/api/v1/users/{admin.id}")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "You cannot deactivate yourself"


async def test_delete_missing_user(make_user: Login, auth_client: AuthClient) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)
    resp = await client.delete("/api/v1/users/999999")
    assert resp.status_code == 404


async def test_delete_as_member_forbidden(make_user: Login, auth_client: AuthClient) -> None:
    member = await make_user(email="member@example.com")
    target = await make_user(email="target@example.com")
    client = await auth_client(member)
    resp = await client.delete(f"/api/v1/users/{target.id}")
    assert resp.status_code == 403


# --- confirmation flow --------------------------------------------------


async def _enable_confirmation(session: AsyncSession) -> None:
    settings_row = await session.get(AppSettings, APP_SETTINGS_ID)
    if settings_row is None:
        settings_row = AppSettings(id=APP_SETTINGS_ID, require_confirmation=True)
        session.add(settings_row)
    else:
        settings_row.require_confirmation = True
    await session.commit()


async def _confirmation_count(session: AsyncSession, user_id: int) -> int:
    query = (
        select(func.count())
        .select_from(ConfirmationToken)
        .where(ConfirmationToken.user_id == user_id)
    )
    return await session.scalar(query) or 0


async def test_create_user_confirmation_on_starts_waiting_and_emails(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    await _enable_confirmation(db_session)
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "newbie@example.com", "first_name": "New", "last_name": "Member"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "waiting_confirmation"
    assert body["confirmed_at"] is None
    assert await _confirmation_count(db_session, body["id"]) == 1
    assert len(smtp) == 1
    assert smtp[0]["To"] == "newbie@example.com"


async def test_create_user_confirmation_on_ignores_password(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    # A password in the payload is ignored; login must fail until they confirm.
    await _enable_confirmation(db_session)
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    await client.post(
        "/api/v1/users",
        json={
            "email": "newbie@example.com",
            "first_name": "New",
            "last_name": "Member",
            "password": "password12345",
        },
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "newbie@example.com", "password": "password12345"},
    )
    assert login.status_code == 401


async def test_create_user_confirmation_on_without_smtp_rejected(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    # Defensive guard: confirmation enabled but SMTP unset (no smtp fixture).
    await _enable_confirmation(db_session)
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "newbie@example.com", "first_name": "New", "last_name": "Member"},
    )
    assert resp.status_code == 400


async def test_create_user_no_password_when_confirmation_off_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    client = await auth_client(admin)

    resp = await client.post(
        "/api/v1/users",
        json={"email": "newbie@example.com", "first_name": "New", "last_name": "Member"},
    )
    assert resp.status_code == 400


async def test_force_active_unconfirmed_allowed(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    # The status Select applies as-is (no coercion): an admin may force a
    # never-confirmed user active. confirmed_at stays null (the UI warns).
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", status=UserStatus.waiting_confirmation)
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"status": "active"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
    assert resp.json()["confirmed_at"] is None


async def test_update_to_waiting_resends_confirmation(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"status": "waiting_confirmation"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "waiting_confirmation"
    assert await _confirmation_count(db_session, member.id) == 1
    assert len(smtp) == 1


async def test_resend_confirmation(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", status=UserStatus.waiting_confirmation)
    client = await auth_client(admin)

    resp = await client.post(f"/api/v1/users/{member.id}/resend-confirmation")

    assert resp.status_code == 204
    assert await _confirmation_count(db_session, member.id) == 1
    assert len(smtp) == 1
    assert smtp[0]["To"] == "member@example.com"


async def test_resend_confirmation_not_waiting_rejected(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")  # active
    client = await auth_client(admin)

    resp = await client.post(f"/api/v1/users/{member.id}/resend-confirmation")
    assert resp.status_code == 400


async def test_resend_confirmation_without_smtp_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", status=UserStatus.waiting_confirmation)
    client = await auth_client(admin)

    resp = await client.post(f"/api/v1/users/{member.id}/resend-confirmation")
    assert resp.status_code == 400


async def test_resend_confirmation_as_member_forbidden(
    make_user: Login, auth_client: AuthClient, smtp: list
) -> None:
    member = await make_user(email="member@example.com")
    target = await make_user(email="target@example.com", status=UserStatus.waiting_confirmation)
    client = await auth_client(member)
    resp = await client.post(f"/api/v1/users/{target.id}/resend-confirmation")
    assert resp.status_code == 403


async def test_deactivate_revokes_confirmation_tokens(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    # A disabled account must not be re-activatable via a still-valid emailed
    # confirmation link, so disabling revokes outstanding confirmation tokens.
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", status=UserStatus.waiting_confirmation)
    client = await auth_client(admin)
    await client.post(f"/api/v1/users/{member.id}/resend-confirmation")
    assert await _confirmation_count(db_session, member.id) == 1

    resp = await client.delete(f"/api/v1/users/{member.id}")

    assert resp.status_code == 204
    assert await _confirmation_count(db_session, member.id) == 0


async def test_update_to_disabled_revokes_confirmation_tokens(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession, smtp: list
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com", status=UserStatus.waiting_confirmation)
    client = await auth_client(admin)
    await client.post(f"/api/v1/users/{member.id}/resend-confirmation")
    assert await _confirmation_count(db_session, member.id) == 1

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"status": "disabled"})

    assert resp.status_code == 200
    assert await _confirmation_count(db_session, member.id) == 0


async def test_update_to_waiting_without_smtp_rejected(
    make_user: Login, auth_client: AuthClient
) -> None:
    # No smtp fixture -> SMTP unconfigured; moving to waiting_confirmation is
    # refused so the user isn't stranded with no way to confirm.
    admin = await make_user(email="admin@example.com", is_admin=True)
    member = await make_user(email="member@example.com")
    client = await auth_client(admin)

    resp = await client.patch(f"/api/v1/users/{member.id}", json={"status": "waiting_confirmation"})
    assert resp.status_code == 400
