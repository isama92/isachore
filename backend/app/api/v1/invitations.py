from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, SessionDep
from app.core.households import add_member, is_active_member
from app.models import HouseholdInvitation, HouseholdInvitationStatus
from app.schemas import HouseholdInvitationInfo, HouseholdMemberRead

router = APIRouter()

# Unknown, expired, and deleted-household all collapse to one 404 so the link
# doesn't leak which case it is (mirrors the confirmation flow).
_invalid_token_exc = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or expired invitation link"
)


async def _resolve_token(session: SessionDep, token: str) -> HouseholdInvitation | None:
    """A still-pending invitation for an active household, with household +
    inviter eager-loaded (async has no lazy loading). Accepted, revoked, and
    expired invites all resolve to None -> the same opaque 404, which also keeps
    the link single-use (an accepted invite can't be redeemed again). Expiry is
    a stored status (the hourly sweep flips pending -> expired), so this trusts
    `status` rather than re-checking `expires_at`."""
    result = await session.execute(
        select(HouseholdInvitation)
        .options(
            joinedload(HouseholdInvitation.household),
            joinedload(HouseholdInvitation.inviter),
        )
        .where(
            HouseholdInvitation.token == token,
            HouseholdInvitation.status == HouseholdInvitationStatus.pending,
        )
    )
    invitation = result.scalar_one_or_none()
    if invitation is None or invitation.household.deleted_at is not None:
        return None
    return invitation


@router.get("/{token}", response_model=HouseholdInvitationInfo)
async def invitation_info(token: str, session: SessionDep) -> HouseholdInvitationInfo:
    """Public: what the accept page shows before the recipient joins."""
    invitation = await _resolve_token(session, token)
    if invitation is None:
        raise _invalid_token_exc
    return HouseholdInvitationInfo(
        household_name=invitation.household.name,
        invited_by=HouseholdMemberRead.model_validate(invitation.inviter),
    )


@router.post("/{token}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invitation(token: str, user: CurrentUser, session: SessionDep) -> None:
    """The logged-in recipient joins the household; the invite is single-use."""
    invitation = await _resolve_token(session, token)
    if invitation is None:
        raise _invalid_token_exc
    if await is_active_member(session, invitation.household_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of this household",
        )
    await add_member(session, invitation.household_id, user.id)
    # Flip to accepted (not deleted): keeps the invite in the owner's list as a
    # record and makes it single-use (resolve now requires pending).
    invitation.status = HouseholdInvitationStatus.accepted
    await session.commit()
