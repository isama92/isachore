# Importing this package registers every model on Base.metadata
# (alembic autogenerate and relationship resolution rely on it).
from app.models.app_settings import AppSettings
from app.models.audit_event import AuditAction, AuditEvent
from app.models.auth_token import AuthToken
from app.models.chore import AssignmentType, Chore, RepeatPeriod
from app.models.chore_occurrence import ChoreOccurrence, OccurrenceStatus
from app.models.confirmation_token import ConfirmationToken
from app.models.household import Household, HouseholdRole, household_members
from app.models.household_invitation import HouseholdInvitation, HouseholdInvitationStatus
from app.models.tag import Tag
from app.models.two_factor_challenge import TwoFactorChallenge
from app.models.two_factor_recovery_code import TwoFactorRecoveryCode
from app.models.user import User, UserStatus

__all__ = [
    "AppSettings",
    "AssignmentType",
    "AuditAction",
    "AuditEvent",
    "AuthToken",
    "Chore",
    "ChoreOccurrence",
    "ConfirmationToken",
    "Household",
    "HouseholdInvitation",
    "HouseholdInvitationStatus",
    "HouseholdRole",
    "OccurrenceStatus",
    "RepeatPeriod",
    "Tag",
    "TwoFactorChallenge",
    "TwoFactorRecoveryCode",
    "User",
    "UserStatus",
    "household_members",
]
