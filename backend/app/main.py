import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.db.redis import redis_client

# INFO so the app.audit trail (M3) is emitted alongside the DB records.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()


app = FastAPI(title="isachore API", version="0.1.0", lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")
