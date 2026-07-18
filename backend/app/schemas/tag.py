from pydantic import BaseModel, ConfigDict, Field

# A tag colour is a #RRGGBB hex string (matches the model's String(7) column).
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str


class TagCreate(BaseModel):
    household_id: int
    name: str = Field(min_length=1, max_length=50)
    color: str = Field(pattern=HEX_COLOR)


class TagUpdate(BaseModel):
    """Full replace of an editable tag. The household is fixed at creation and
    intentionally not editable here (mirrors ChoreUpdate)."""

    name: str = Field(min_length=1, max_length=50)
    color: str = Field(pattern=HEX_COLOR)
