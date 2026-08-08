from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """The body FastAPI sends for a raised `HTTPException`.

    Declared so a refusal can be documented as carrying its explanation rather than as
    bodyless, which is what a route with only a `description` claims. Every hand-raised
    HTTPException in this app answers in this shape; only the routes that declare it say
    so, and wiring that up everywhere is the job of the security-scheme step in README's
    todo rather than of any single endpoint.
    """

    detail: str
