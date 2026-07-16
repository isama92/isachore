from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_token, hash_token
from app.models import AuthToken, User

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


def _png_bytes(
    size: tuple[int, int] = (24, 16), color: tuple[int, int, int] = (200, 30, 30)
) -> bytes:
    """A real (non-square, to exercise the crop) PNG."""
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def avatar_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point avatar storage at a throwaway tmp dir so tests write nothing into
    the repo. avatars_dir() reads settings at call time, so this takes effect."""
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    return tmp_path / "avatars"


# --- name -----------------------------------------------------------------


async def test_update_name(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user()
    client = await auth_client(user)

    res = await client.patch("/api/v1/profile", json={"name": "Renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"
    assert res.json()["avatar_url"] is None
    # A name-only edit must not touch sessions.
    assert await _token_count(db_session, user.id) == 1


async def test_update_profile_requires_auth(client: AsyncClient) -> None:
    assert (await client.patch("/api/v1/profile", json={"name": "x"})).status_code == 401
    assert (await client.delete("/api/v1/profile/avatar")).status_code == 401
    res = await client.put(
        "/api/v1/profile/avatar", files={"file": ("a.png", _png_bytes(), "image/png")}
    )
    assert res.status_code == 401


# --- password -------------------------------------------------------------


async def test_change_password_keeps_current_session_revokes_others(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user(password="oldpassword123")
    client = await auth_client(user)  # this device's token
    await _issue_token(db_session, user)  # a second device
    assert await _token_count(db_session, user.id) == 2

    res = await client.patch(
        "/api/v1/profile",
        json={"current_password": "oldpassword123", "new_password": "newpassword456"},
    )
    assert res.status_code == 200
    # Only the current device's token survives.
    assert await _token_count(db_session, user.id) == 1
    # ...and the current session is still usable.
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    # New password works, old one no longer does.
    ok = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "newpassword456"}
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "oldpassword123"}
    )
    assert bad.status_code == 401


async def test_change_password_wrong_current(
    make_user: Login, auth_client: AuthClient, db_session: AsyncSession
) -> None:
    user = await make_user(password="oldpassword123")
    client = await auth_client(user)

    res = await client.patch(
        "/api/v1/profile",
        json={"current_password": "wrongpassword", "new_password": "newpassword456"},
    )
    assert res.status_code == 400
    # Password unchanged and no sessions revoked.
    assert await _token_count(db_session, user.id) == 1
    ok = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "oldpassword123"}
    )
    assert ok.status_code == 200


async def test_change_password_missing_current(make_user: Login, auth_client: AuthClient) -> None:
    user = await make_user()
    client = await auth_client(user)
    res = await client.patch("/api/v1/profile", json={"new_password": "newpassword456"})
    assert res.status_code == 422


async def test_new_password_too_short(make_user: Login, auth_client: AuthClient) -> None:
    user = await make_user(password="oldpassword123")
    client = await auth_client(user)
    res = await client.patch(
        "/api/v1/profile",
        json={"current_password": "oldpassword123", "new_password": "short"},
    )
    assert res.status_code == 422


# --- avatar ---------------------------------------------------------------


async def test_upload_avatar(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path
) -> None:
    user = await make_user()
    client = await auth_client(user)

    res = await client.put(
        "/api/v1/profile/avatar", files={"file": ("photo.png", _png_bytes(), "image/png")}
    )
    assert res.status_code == 200
    url = res.json()["avatar_url"]
    assert url.startswith("/api/v1/media/avatars/") and url.endswith(".webp")
    # The processed file is on disk.
    filename = url.rsplit("/", 1)[-1]
    assert (avatar_storage / filename).is_file()
    # ...and /auth/me exposes the same URL (computed field propagates to MeRead).
    me = await client.get("/api/v1/auth/me")
    assert me.json()["avatar_url"] == url


async def test_upload_avatar_rejects_non_image(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path
) -> None:
    user = await make_user()
    client = await auth_client(user)
    res = await client.put(
        "/api/v1/profile/avatar",
        files={"file": ("evil.png", b"definitely not an image", "image/png")},
    )
    assert res.status_code == 400
    # Nothing landed on disk and nothing was recorded on the user. (glob on a
    # missing dir yields nothing, so this holds whether or not the dir exists.)
    assert list(avatar_storage.glob("*")) == []
    me = await client.get("/api/v1/auth/me")
    assert me.json()["avatar_url"] is None


async def test_upload_avatar_rejects_corrupt_image(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path
) -> None:
    # A file with a valid PNG header but a corrupted body: Pillow recognises it
    # then fails to decode (raises SyntaxError). Must be a clean 400, not a 500.
    corrupt = bytearray(_png_bytes(size=(8, 8)))
    corrupt[len(corrupt) // 2] ^= 0xFF
    user = await make_user()
    client = await auth_client(user)
    res = await client.put(
        "/api/v1/profile/avatar", files={"file": ("corrupt.png", bytes(corrupt), "image/png")}
    )
    assert res.status_code == 400
    assert list(avatar_storage.glob("*")) == []


async def test_upload_avatar_replaces_and_deletes_old(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path
) -> None:
    user = await make_user()
    client = await auth_client(user)

    first = (
        (
            await client.put(
                "/api/v1/profile/avatar", files={"file": ("a.png", _png_bytes(), "image/png")}
            )
        )
        .json()["avatar_url"]
        .rsplit("/", 1)[-1]
    )
    second = (
        (
            await client.put(
                "/api/v1/profile/avatar", files={"file": ("b.png", _png_bytes(), "image/png")}
            )
        )
        .json()["avatar_url"]
        .rsplit("/", 1)[-1]
    )

    assert first != second
    assert not (avatar_storage / first).exists()
    assert (avatar_storage / second).is_file()


async def test_upload_avatar_too_large(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "avatar_max_bytes", 10)
    user = await make_user()
    client = await auth_client(user)
    res = await client.put(
        "/api/v1/profile/avatar", files={"file": ("big.png", _png_bytes(), "image/png")}
    )
    assert res.status_code == 413


async def test_upload_avatar_too_many_pixels(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guard against decompression bombs: reject on decoded pixel count (the
    # 24x16 png is 384 px, well over this tiny ceiling) with a clean 400.
    monkeypatch.setattr(settings, "avatar_max_pixels", 4)
    user = await make_user()
    client = await auth_client(user)
    res = await client.put(
        "/api/v1/profile/avatar", files={"file": ("big.png", _png_bytes(), "image/png")}
    )
    assert res.status_code == 400
    assert list(avatar_storage.glob("*")) == []


async def test_delete_avatar(
    make_user: Login, auth_client: AuthClient, avatar_storage: Path
) -> None:
    user = await make_user()
    client = await auth_client(user)
    filename = (
        (
            await client.put(
                "/api/v1/profile/avatar", files={"file": ("a.png", _png_bytes(), "image/png")}
            )
        )
        .json()["avatar_url"]
        .rsplit("/", 1)[-1]
    )
    assert (avatar_storage / filename).is_file()

    res = await client.delete("/api/v1/profile/avatar")
    assert res.status_code == 200
    assert res.json()["avatar_url"] is None
    assert not (avatar_storage / filename).exists()


async def test_delete_avatar_idempotent_when_none(
    make_user: Login, auth_client: AuthClient
) -> None:
    user = await make_user()
    client = await auth_client(user)
    res = await client.delete("/api/v1/profile/avatar")
    assert res.status_code == 200
    assert res.json()["avatar_url"] is None
