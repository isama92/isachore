from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas import HealthRead

router = APIRouter()


# The handler returns a JSONResponse so it can pick the status code per branch, and a bare
# `-> JSONResponse` tells the schema generator nothing: it documents an unconstrained 200
# and hides the 503 entirely. Returning a Response directly also skips response_model
# validation, so both declarations below are documentation and cannot reshape the body.
@router.get(
    "/health",
    response_model=HealthRead,
    responses={503: {"model": HealthRead, "description": "The database is unreachable"}},
)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> JSONResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
    return JSONResponse(content={"status": "ok", "database": "ok"})
