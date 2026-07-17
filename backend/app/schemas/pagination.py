from pydantic import BaseModel


class Page[T](BaseModel):
    """Envelope for a server-side-paginated list response. `total` is the count
    across all pages (with the same filters applied), so the client can render
    pagination without fetching every row."""

    items: list[T]
    total: int
    page: int
    page_size: int
