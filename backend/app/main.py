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
app.mount(
    "/api/v1/media/avatars",
    StaticFiles(directory=avatars_dir(), check_dir=False),
    name="avatars",
)
