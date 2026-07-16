import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.avatars import avatars_dir
from app.db.redis import redis_client

# INFO so the app.audit trail (M3) is emitted alongside the DB records.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()


app = FastAPI(title="isachore API", version="0.1.0", lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")

# Serve uploaded avatars under the /api prefix so the prod nginx /api proxy
# reaches them untouched. Mount the avatars folder specifically (not the whole
# storage dir) so nothing else placed under storage/ is ever web-reachable.
# avatars_dir() also ensures the folder exists before StaticFiles binds to it.
# AVG note: avatars are personal data served without an auth check, protected
# only by an unguessable 128-bit random filename (draft pending VCSW jurist
# sign-off; revisit if avatars must sit inside the auth boundary).
app.mount(
    "/api/v1/media/avatars",
    StaticFiles(directory=avatars_dir(), check_dir=False),
    name="avatars",
)
