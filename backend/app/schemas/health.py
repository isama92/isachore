from typing import Literal

from pydantic import BaseModel


class HealthRead(BaseModel):
    """What the probe reports.

    `database` names the subsystem rather than only the verdict, so a 503 says *what* is
    down; the endpoint answers with this shape on both codes.
    """

    status: Literal["ok", "error"]
    database: Literal["ok", "unreachable"]
