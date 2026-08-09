"""A 422 says what was wrong with the request, never what the request contained.

Pydantic's stock handler returns an `input` key holding the rejected value, so a password
below `min_length=8` came back in the response body in plaintext. Nothing in the app rendered
it, which is why it went unnoticed: the exposure is on the wire and in anything that records
response bodies - a reverse proxy access log, an error tracker, a browser devtools export
attached to a support ticket.

The tests below assert the *property* rather than the mechanism. Checking that the `input`
key is gone would pass if a future pydantic moved the value into `ctx` instead, so each one
also asserts the secret appears nowhere in the body at all.
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models import User

MakeUser = Callable[..., Awaitable[User]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

# Distinctive enough that finding it anywhere in a response body is unambiguous, and SEVEN
# characters, which is what makes it fail the 8-character minimum and reach the 422 at all.
# The first draft of this used an eight-character string: every endpoint accepted it, the
# tests went looking for a 422 that never happened, and had they been written to tolerate
# that they would have proved nothing.
SECRET = "sh0rtpw"


async def test_a_rejected_password_is_not_echoed_by_the_confirmation_endpoint(
    client: AsyncClient,
) -> None:
    """Public and unauthenticated, so this body is the easiest of the three to capture."""
    response = await client.post("/api/v1/confirm/whatever", json={"password": SECRET})

    assert response.status_code == 422
    assert SECRET not in response.text
    assert all("input" not in error for error in response.json()["detail"])


async def test_a_rejected_password_is_not_echoed_by_admin_user_creation(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    """`UserCreate.password` carries the same `min_length=8`, so this route reached the echo
    too - and it was missing from the first version of this file and from the three places
    that listed the affected routes. A set claimed complete is the shape that rots."""
    admin = await make_user(email="admin@example.com", is_admin=True)
    signed_in = await auth_client(admin)

    response = await signed_in.post(
        "/api/v1/admin/users",
        json={
            "email": "new@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": SECRET,
        },
    )

    assert response.status_code == 422
    assert SECRET not in response.text


async def test_a_rejected_password_is_not_echoed_by_the_admin_user_update(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    target = await make_user(email="alice@example.com")
    signed_in = await auth_client(admin)

    response = await signed_in.patch(f"/api/v1/admin/users/{target.id}", json={"password": SECRET})

    assert response.status_code == 422
    assert SECRET not in response.text


async def test_a_rejected_password_is_not_echoed_by_the_profile_update(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    user = await make_user(email="alice@example.com")
    signed_in = await auth_client(user)

    # `new_password`, not `password`: the self-service schema names it differently from the
    # admin one, and pydantic ignores the unknown key rather than refusing it - so sending
    # `password` here answers 200 and the test proves nothing.
    response = await signed_in.patch(
        "/api/v1/profile", json={"current_password": "password12345", "new_password": SECRET}
    )

    assert response.status_code == 422
    assert SECRET not in response.text


async def test_the_error_keeps_the_shape_the_frontend_parses(client: AsyncClient) -> None:
    """The half that is easy to break while fixing the half above.

    `lib/validationError.ts` turns this into one translated sentence, and it needs all of it:
    the `detail` ARRAY (flattening it to a string server-side would also take the
    machine-readable form away from non-browser clients), the `type` discriminator it keys
    off rather than the English `msg`, and `ctx`, whose `min_length` it interpolates into
    "at least 8 characters". Dropping `ctx` alongside `input` would look tidier and would
    silently degrade every field error to pydantic's developer-facing wording.
    """
    response = await client.post("/api/v1/confirm/whatever", json={"password": SECRET})

    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["type"] == "string_too_short"
    assert detail[0]["loc"] == ["body", "password"]
    assert detail[0]["msg"]
    assert detail[0]["ctx"] == {"min_length": 8}


async def test_a_value_error_from_our_own_validators_still_serialises(
    client: AsyncClient,
) -> None:
    """`jsonable_encoder` is not decoration.

    A `value_error` - what the hand-written validators in `schemas/` raise - carries the
    original exception object in `ctx`, which `json.dumps` cannot take. The stock handler
    encodes before responding and so must this one; without it the endpoint answers 500 while
    trying to explain a 422.
    """
    response = await client.post("/api/v1/auth/login", json={"email": "nope", "password": "x"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "value_error"


def test_the_spec_does_not_advertise_the_rejected_value() -> None:
    """FastAPI publishes `input` as a property of `ValidationError` because its own handler
    sends one. Ours does not, so the document must not say otherwise - and this is also what
    turns a FastAPI rename of that schema into a failing test rather than a quietly restored
    field, since `_openapi_without_the_rejected_value` looks it up defensively."""
    from app.main import app

    validation_error = app.openapi()["components"]["schemas"]["ValidationError"]
    assert "input" not in validation_error["properties"]
    # The rest of the shape is what the frontend parser depends on; if this ever fails, the
    # pop above found the wrong schema.
    assert set(validation_error["properties"]) >= {"loc", "msg", "type"}
