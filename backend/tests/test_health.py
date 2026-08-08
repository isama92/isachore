import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app


async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_health_reports_an_unreachable_database(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusing branch, which is the whole reason this endpoint picks its own status
    code rather than letting a response model serialise one for it.

    What it guards is a refactor that returns a plain dict to make `response_model` live:
    the status would collapse to the route default and this 503 assertion would fail. It
    cannot tell you whether the model validates today, since both branches satisfy the
    Literals either way - that claim rests on FastAPI skipping the model whenever a handler
    returns a Response itself, which is a property of the framework, not of this test.
    """

    async def unreachable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db_session, "execute", unreachable)

    resp = await client.get("/api/v1/health")

    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "database": "unreachable"}


def test_health_documents_the_body_it_returns_on_both_branches() -> None:
    """The handler returns a bare JSONResponse so it can pick its own status code, and that
    annotation tells the schema generator nothing: left to infer, it documents an
    unconstrained 200 and omits the 503 entirely, so a consumer reading the spec learns
    neither the shape nor that the endpoint can refuse. Routes are read off `openapi()`
    rather than `app.routes` because FastAPI registers included routers lazily.
    """
    responses = app.openapi()["paths"]["/api/v1/health"]["get"]["responses"]

    assert set(responses) >= {"200", "503"}
    for code in ("200", "503"):
        body = responses[code].get("content", {}).get("application/json", {})
        assert body.get("schema", {}).get("$ref", "").endswith("/HealthRead"), (
            f"{code} does not name a body shape"
        )
