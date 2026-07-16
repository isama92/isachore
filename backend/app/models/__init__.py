# Importing this package registers every model on Base.metadata
# (alembic autogenerate and relationship resolution rely on it).
from app.models.auth_token import AuthToken
from app.models.chore import AssignmentType, Chore, RepeatPeriod
from app.models.household import Household, household_members
from app.models.tag import Tag
from app.models.user import User

__all__ = [
    "AssignmentType",
    "AuthToken",
    "Chore",
    "Household",
    "RepeatPeriod",
    "Tag",
    "User",
    "household_members",
]
