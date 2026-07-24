import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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


app = FastAPI(title="isachore API", version="0.1.0", lifespan=lifespan)
# Transport-level request body cap (max_request_bytes); defence in depth behind
# the prod nginx client_max_body_size for deployments without a proxy in front.
app.add_middleware(BodySizeLimitMiddleware)
# Custom-header CSRF defence (L4). Added last so it is the outermost middleware:
# a forged cookie-authenticated mutation is rejected before its body is spooled.
app.add_middleware(CsrfProtectMiddleware)
app.include_router(api_router, prefix="/api/v1")

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
# UserRead.avatar_url, which every route exposing it puts behind auth. So the
# holders are the user, admins, and household peers (ChoreRead embeds its
# assignees), all of whom see the picture in the UI regardless. Uploads are
# re-encoded to WebP and Pillow carries no metadata across, since _process passes
# only format and quality, so a leaked file discloses the picture and nothing
# about where or when it was taken.
#
# Note this does NOT lean on Referrer-Policy, despite that header being set
# (frontend/nginx-common.conf, prod only): an avatar URL appears solely as an
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
