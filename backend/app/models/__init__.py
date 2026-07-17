# Importing this package registers every model on Base.metadata
# (alembic autogenerate and relationship resolution rely on it).
from app.models.app_settings import AppSettings
from app.models.audit_event import AuditAction, AuditEvent
from app.models.auth_token import AuthToken
from app.models.chore import AssignmentType, Chore, RepeatPeriod
from app.models.confirmation_token import ConfirmationToken
from app.models.household import Household, household_members
from app.models.household_invitation import HouseholdInvitation, HouseholdInvitationStatus
from app.models.tag import Tag
from app.models.user import User, UserStatus

__all__ = [
    "AppSettings",
    "AssignmentType",
    "AuditAction",
    "AuditEvent",
    "AuthToken",
    "Chore",
    "ConfirmationToken",
    "Household",
    "HouseholdInvitation",
    "HouseholdInvitationStatus",
    "RepeatPeriod",
    "Tag",
    "User",
    "UserStatus",
    "household_members",
]
