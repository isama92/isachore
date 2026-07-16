from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.user import UserRead


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    members: list[UserRead]
