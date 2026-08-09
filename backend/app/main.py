import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.docs import page_router as docs_page_router
from app.api.v1.router import api_router
from app.core.avatars import avatars_dir
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.csrf import CsrfProtectMiddleware
from app.core.scheduler import create_scheduler
from app.core.startup import enforce_startup_config
from app.db.redis import redis_client

# INFO so the app.audit trail (M3) is emitted alongside the DB records.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Refuse to serve a misconfigured non-dev deploy (I1) before anything else
    # starts. Only the web process is gated: `python -m app.cli` and alembic do
    # not run the lifespan, so they still work to repair what this rejected.
    enforce_startup_config()
    # Recurring background jobs (e.g. expiring stale invitations) run inside the
    # web process; started here and stopped on shutdown.
    scheduler = create_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await redis_client.aclose()


# The description carries the one authentication rule the generated document cannot state
# for itself. FastAPI emits one `security` entry per scheme and OpenAPI reads separate
# entries as ALTERNATIVES, so declaring X-CSRF-Token as a scheme alongside `sessionCookie`
# would publish "cookie or header" - the opposite of what CsrfProtectMiddleware enforces,
# which is both together. Prose here rather than a scheme that lies; see api/deps.py.
API_DESCRIPTION = """\
Chore management for households.

## Authenticating

Two transports, either of which carries a session:

- the httpOnly `isachore_token` cookie, which a browser sends on its own, and
- the same opaque token as an `Authorization: Bearer` header, for clients with no cookie jar.

Two ways to open one, and nothing downstream can tell them apart. `POST /api/v1/auth/login`
takes an email and password, and answers `two_factor_required` instead of a session when the
account has TOTP enabled - finish that with `POST /api/v1/auth/verify-2fa`. Where single
sign-on is configured, `GET /api/v1/auth/oidc/start` is the other way in, and on a server
with `OIDC_ONLY` set it is the only one: password login answers 403 there.
`GET /api/v1/auth/methods` says which of the two this server offers, without a session.

There is no self-registration: administrators create accounts, and the first administrator
comes from the `init` CLI command.

## The CSRF header

A request authenticated **by cookie** that uses an unsafe method (POST, PATCH, PUT, DELETE)
must also carry a non-empty `X-CSRF-Token` header, or it is refused with 403 before it
reaches the route. Any value will do: this is a custom-header defence over `SameSite=Lax`,
so what matters is that a cross-site form cannot set the header at all.

`Authorization: Bearer` requests are exempt, as are requests carrying no auth cookie.
"""

# `redoc_url=None` because api/v1/docs.py serves that page instead, from a vendored bundle
# with no third-party requests at all. Swagger UI keeps FastAPI's own page and its CDN: no
# deployment exposes it (the prod nginx proxies the reference and nothing else), so it costs
# only a developer's own machine, and it is the one reader with a "Try it out" console.
app = FastAPI(
    title="isachore API",
    version="0.1.0",
    description=API_DESCRIPTION,
    lifespan=lifespan,
    redoc_url=None,
)


@app.exception_handler(RequestValidationError)
async def strip_the_rejected_value(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's own 422, minus pydantic's echo of what the caller sent.

    The stock handler returns each error with an `input` key holding the value that failed,
    which for a password below `min_length=8` means the password comes back in the response
    body in plaintext. Four routes take a constrained password and so reach it: `POST
    /confirm/{token}`, `POST /admin/users`, `PATCH /admin/users/{id}` and the profile password
    change. Nothing in the app was ever showing it (`validationError.ts`
    reads `type`, `loc`, `msg` and `ctx`), so this is a wire and log-capture exposure rather
    than a visible one, but a proxy access log or an error tracker that records response
    bodies keeps it.

    Two things stay exactly as they were, and both are load-bearing:

    - **the array shape.** `detail` is a *list* of `{loc, msg, type, ctx}`, which
      `lib/validationError.ts` parses into one translated sentence. `/api/v1` also has future
      non-browser clients, so flattening it to a string server-side would take the
      machine-readable form away from them.
    - **`ctx`.** The frontend interpolates `ctx.min_length`, `ctx.max_length` and
      `ctx.expected` into those sentences, so dropping it would silently degrade every field
      error to pydantic's developer-facing English.

    `jsonable_encoder` is what the stock handler uses and is not optional: a `value_error`
    carries the original exception object in `ctx`, which is not JSON on its own.
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": jsonable_encoder(
                [
                    {key: value for key, value in error.items() if key != "input"}
                    for error in exc.errors()
                ]
            )
        },
    )


def _openapi_without_the_rejected_value() -> dict[str, Any]:
    """The generated document, minus the `input` property the handler above never sends.

    FastAPI's published `ValidationError` schema lists `input` as an optional property,
    because its stock handler does return one. Removing it from the body and leaving the
    schema alone would swap one lie for another - a document advertising a field the API
    never produces - which is exactly the defect the rest of this work exists to remove.

    Written defensively rather than with a bare subscript: this runs whenever anybody fetches
    /openapi.json, and a KeyError there would be a 500 on a live deployment if FastAPI ever
    renamed the schema. `test_the_spec_does_not_advertise_the_rejected_value` is what turns
    that rename into a failing test instead of a silently-restored field.
    """
    schema = _generate_openapi()
    validation_error = schema.get("components", {}).get("schemas", {}).get("ValidationError", {})
    validation_error.get("properties", {}).pop("input", None)
    return schema


_generate_openapi = app.openapi
app.openapi = _openapi_without_the_rejected_value  # type: ignore[method-assign]

# Transport-level request body cap (max_request_bytes); defence in depth behind
# the prod nginx client_max_body_size for deployments without a proxy in front.
app.add_middleware(BodySizeLimitMiddleware)
# Custom-header CSRF defence (L4). Added last so it is the outermost middleware:
# a forged cookie-authenticated mutation is rejected before its body is spooled.
app.add_middleware(CsrfProtectMiddleware)
app.include_router(api_router, prefix="/api/v1")
# At the ROOT, not under /api/v1, and that is load-bearing: the prod nginx gates one exact
# location (`= /docs`, rewritten here) while proxying all of /api/ ungated, so a reference
# page under the API prefix would be readable by anybody. See api/v1/docs.py.
app.include_router(docs_page_router)

# Serve uploaded avatars under the /api prefix so the prod nginx /api proxy
# reaches them untouched. Mount the avatars folder specifically (not the whole
# storage dir) so nothing else placed under storage/ is ever web-reachable.
# avatars_dir() also ensures the folder exists before StaticFiles binds to it.
#
# ACCEPTED RISK (I3): this mount is unauthenticated by design, so anyone holding
# a URL can fetch that image until the avatar is deleted or replaced (both unlink
# the old file, see api/v1/profile.py). That is the accepted downside; what makes
# it narrow is that the URL is a capability, not a guessable path. The filename is
# 128 bits from secrets.token_hex(16) (core/avatars.py) and carries no user id,
# StaticFiles serves no directory listing, and the name is only ever returned by
# UserRead.avatar_url, which every route exposing it puts behind auth. So the holders
# are the user themselves (profile, auth, two-factor and the signup confirmation) and
# site admins (the admin users router), both of whom see the picture in the UI regardless.
# Household peers do NOT hold one: ChoreRead used to embed its assignees as full
# UserReads, which made it the only route handing a UserRead to a household peer, and
# it now uses HouseholdMemberRead (id and names, no avatar) - so keep any new payload
# reaching household peers off UserRead, or this reasoning stops holding. Uploads are
# re-encoded to WebP and Pillow carries no metadata across, since _process passes
# only format and quality, so a leaked file discloses the picture and nothing
# about where or when it was taken.
#
# Note this does NOT lean on Referrer-Policy, despite that header being set
# (docker/nginx/nginx-common.conf, prod only): an avatar URL appears solely as an
# <img src>, and a Referer carries the referring document's URL, never a
# subresource's, so the header only covers opening the image as a document and
# then following an off-site link from it.
#
# Judged a reasonable trade for profile pictures. Gating them means either an auth
# dependency on every <img> (same-origin, so the cookie is sent, but it puts every
# avatar request through a DB token lookup) or signed expiring URLs. Revisit if
# uploads ever carry anything more sensitive than a profile picture.
app.mount(
    "/api/v1/media/avatars",
    StaticFiles(directory=avatars_dir(), check_dir=False),
    name="avatars",
)
