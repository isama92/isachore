from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HouseholdMemberRead(BaseModel):
    # Only what the assignee picker needs (data minimisation: no email here).
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    members: list[HouseholdMemberRead]
