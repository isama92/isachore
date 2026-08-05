from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, SessionDep
from app.core import clock
from app.core.config import settings
from app.core.households import (
    HOUSEHOLD_SORT_COLUMNS,
    MEMBER_SORT_COLUMNS,
    add_member,
    chore_count_column,
    escape_like,
    household_zone,
    is_active_member,
    member_count_column,
    member_of,
    require_role,
    role_in_household,
)
from app.core.invitations import round_up_to_hour
from app.core.occurrences import reanchor_open_occurrences
from app.core.security import INVITATION_TOKEN_TTL, generate_token
from app.models import (
    Household,
    HouseholdInvitation,
    HouseholdInvitationStatus,
    HouseholdRole,
    User,
    UserStatus,
    household_members,
)
from app.schemas import (
    HouseholdCreate,
    HouseholdInvitationRead,
    HouseholdListRead,
    HouseholdMemberRoleRead,
    HouseholdMemberUpdate,
    HouseholdUpdate,
    Page,
)

router = APIRouter()

HouseholdSortBy = Literal["id", "name", "created_at"]
MemberSortBy = Literal["id", "name"]
SortDir = Literal["asc", "desc"]

# The most outstanding (pending) invitations a household may have at once; someone must
# revoke one (or have it accepted) to add more. Per household, not per inviter, so the
# organisers who can now invite share one budget.
MAX_PENDING_INVITATIONS = 5


# --- shared page builders (reused by the admin router) ------------------


async def build_household_page(
    session: SessionDep,
    *,
    extra_filters: Sequence[ColumnElement[bool]],
    page: int,
    page_size: int,
    sort_by: str,
    sort_dir: str,
    name: str | None,
) -> Page[HouseholdListRead]:
    """List households (with member/chore counts) as a paginated envelope.

    `extra_filters` scopes the result (e.g. only my households, only active) and
    is applied to both the count and the page query, exactly like list_users.
    """
    filters = list(extra_filters)
    if name and name.strip():
        filters.append(Household.name.ilike(f"%{escape_like(name.strip())}%"))

    count_query = select(func.count()).select_from(Household)
    list_query = select(
        Household,
        member_count_column().label("member_count"),
        chore_count_column().label("chore_count"),
    )
    if filters:
        count_query = count_query.where(*filters)
        list_query = list_query.where(*filters)

    total = await session.scalar(count_query) or 0

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in HOUSEHOLD_SORT_COLUMNS[sort_by]]
    # Deterministic tiebreaker so paging is stable when the sort key ties.
    order_by.append(Household.id.desc() if descending else Household.id.asc())

    result = await session.execute(
        list_query.order_by(*order_by).limit(page_size).offset((page - 1) * page_size)
    )
    items = [
        HouseholdListRead(
            id=household.id,
            name=household.name,
            admin_id=household.admin_id,
            timezone=household.timezone,
            created_at=household.created_at,
            deleted_at=household.deleted_at,
            member_count=member_count,
            chore_count=chore_count,
        )
        for household, member_count, chore_count in result.all()
    ]
    return Page[HouseholdListRead](items=items, total=total, page=page, page_size=page_size)


async def build_members_page(
    session: SessionDep,
    *,
    household_id: int,
    page: int,
    page_size: int,
    sort_by: str,
    sort_dir: str,
    name: str | None,
) -> Page[HouseholdMemberRoleRead]:
    """Active members of a household, with each one's role, as a paginated envelope.

    The role comes off the association row, so this is the one members payload that
    carries it: `HouseholdMemberRead` is shared with the assignee pickers, History's
    `completed_by` and the invitation page, none of which join a membership at all.
    Roles are not a sort key on purpose - sorting them alphabetically (deputy, helper,
    organiser) would suggest a ranking that isn't one."""
    filters: list[ColumnElement[bool]] = [
        household_members.c.household_id == household_id,
        User.status == UserStatus.active,
    ]
    if name and name.strip():
        pattern = f"%{escape_like(name.strip())}%"
        filters.append(or_(User.first_name.ilike(pattern), User.last_name.ilike(pattern)))

    list_query = (
        select(User, household_members.c.role)
        .join(household_members, household_members.c.user_id == User.id)
        .where(*filters)
    )
    count_query = (
        select(func.count())
        .select_from(User)
        .join(household_members, household_members.c.user_id == User.id)
        .where(*filters)
    )
    total = await session.scalar(count_query) or 0

    descending = sort_dir == "desc"
    order_by = [col.desc() if descending else col.asc() for col in MEMBER_SORT_COLUMNS[sort_by]]
    order_by.append(User.id.desc() if descending else User.id.asc())

    result = await session.execute(
        list_query.order_by(*order_by).limit(page_size).offset((page - 1) * page_size)
    )
    return Page[HouseholdMemberRoleRead](
        items=[
            HouseholdMemberRoleRead(
                id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                role=HouseholdRole(role),
            )
            for user, role in result.all()
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def load_household_read(
    session: SessionDep,
    household_id: int,
    *,
    extra_filters: Sequence[ColumnElement[bool]] = (),
) -> HouseholdListRead:
    """Fetch a single household (with counts) as a read model, or 404.

    `extra_filters` enforces scope/visibility (e.g. mine + not deleted).
    """
    row = (
        await session.execute(
            select(
                Household,
                member_count_column().label("member_count"),
                chore_count_column().label("chore_count"),
            ).where(Household.id == household_id, *extra_filters)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    household, member_count, chore_count = row
    return HouseholdListRead(
        id=household.id,
        name=household.name,
        admin_id=household.admin_id,
        timezone=household.timezone,
        created_at=household.created_at,
        deleted_at=household.deleted_at,
        member_count=member_count,
        chore_count=chore_count,
    )


async def set_household_admin(session: SessionDep, household: Household, new_admin_id: int) -> None:
    """Transfer ownership: the new owner must be an active member of the household.

    Promoting them to organiser is part of the transfer rather than a separate step,
    because the owner is by definition one and their row is the one the role endpoint
    refuses to touch. Hand a helper the household without this and they would own a
    household they cannot manage the chores of, with no way to fix it. The previous
    owner keeps `organiser` and becomes an ordinary one, so the new owner can demote
    them like anybody else."""
    if not await is_active_member(session, household.id, new_admin_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The new household admin must be a member of the household",
        )
    household.admin_id = new_admin_id
    await session.execute(
        update(household_members)
        .where(
            household_members.c.household_id == household.id,
            household_members.c.user_id == new_admin_id,
        )
        .values(role=HouseholdRole.organiser)
    )


async def apply_timezone_change(
    session: SessionDep, household: Household, new_timezone: str | None
) -> int:
    """Move the household to `new_timezone`, re-anchoring its open slots so every scheduled
    chore keeps the local date it already showed. Returns how many moved (0 when the zone was
    omitted or unchanged).

    Shared by the user-facing PATCH and its admin twin so the re-anchor cannot be forgotten on
    one of them - which would leave a household whose chores all silently shift by a day
    depending on which page the change was made from.

    Both guards are about *work*, not correctness. `None` means "not in the payload" on a
    partial update. An unchanged zone would re-anchor every open occurrence onto the instant it
    already holds, which is a no-op the ORM would not even flush - SQLAlchemy issues no UPDATE
    for an attribute set to an equal value, and aware datetimes compare by instant - so nothing
    would be written and `updated_at` would not move either. What the guards save is the query
    per open occurrence that `free_slot_from` costs on the way to that no-op, which a plain
    rename would otherwise pay on every save.
    """
    if new_timezone is None or new_timezone == household.timezone:
        return 0
    old_zone = household_zone(household.timezone)
    household.timezone = new_timezone
    return await reanchor_open_occurrences(
        session, household.id, old_zone, household_zone(new_timezone)
    )


async def commit_household_update(session: SessionDep, *, rescheduled: int) -> None:
    """Commit a household PATCH, mapping a slot collision to a 409 rather than a 500.

    `rescheduled` is what `apply_timezone_change` reported, and gating on it is what keeps the
    message honest: a name-only save touches no occurrence row, so nothing on that path can
    raise this and a caller who somehow saw it would be told a chore was completed when none
    was. No other constraint on this endpoint can realistically raise today, which makes the
    mislabel latent rather than live - but the fix is a branch, so there is no reason to carry it.

    The collision itself needs a genuine race: `free_slot_from` already walks each candidate past
    the slots the chore has completed, so what is left is a completion landing between that walk
    and this commit, which is exactly the shape `update_chore` maps to a 409. Shared by both
    PATCH handlers so the two cannot drift.
    """
    if not rescheduled:
        await session.commit()
        return
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A chore was completed while the timezone was changing; please try again",
        ) from None


def refuse_owner_row(household: Household, user_id: int) -> None:
    """409 if `user_id` owns the household. Their role is derived from owning it, so the way to
    move it is to transfer, which promotes the new owner - and that path exists on both
    surfaces, so the message is actionable for a site admin too.

    A named guard rather than an inline check, because *where* it fires matters: the user
    surface calls it before its organiser rule so an organiser targeting the owner is told about
    the target rather than about themselves, and `set_member_role` calls it again so the admin
    surface gets it without repeating the reasoning."""
    if household.admin_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The household admin is always an organiser; transfer ownership instead",
        )


async def set_member_role(
    session: SessionDep, household: Household, user_id: int, role: HouseholdRole
) -> HouseholdMemberRoleRead:
    """Write one member's role, or 409 / 404. The single chokepoint both surfaces call, so the
    two target rules are enforced once - the same arrangement as `remove_member`.

    Refuses the owner's row (see `refuse_owner_row`) and a disabled member, who keeps their row
    but is hidden everywhere, so re-roling one would change a permission nothing displays.

    What is NOT here is who may call it: the user surface adds the organiser rules on top, the
    admin surface relies on `AdminUser`. Commits, like `remove_member`, because both callers only
    read the household first.
    """
    refuse_owner_row(household, user_id)
    # One query for the 404 guard and for the response, rather than `is_active_member` followed
    # by a second fetch: the membership join is the existence check, and `expire_on_commit=False`
    # (db/session.py) is what lets the row outlive the commit below.
    member = (
        await session.execute(
            select(User)
            .join(household_members, household_members.c.user_id == User.id)
            .where(
                household_members.c.household_id == household.id,
                household_members.c.user_id == user_id,
                User.status == UserStatus.active,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Household member not found"
        )
    await session.execute(
        update(household_members)
        .where(
            household_members.c.household_id == household.id,
            household_members.c.user_id == user_id,
        )
        .values(role=role)
    )
    await session.commit()
    return HouseholdMemberRoleRead(
        id=member.id,
        first_name=member.first_name,
        last_name=member.last_name,
        role=role,
    )


async def remove_member(session: SessionDep, household_id: int, user_id: int) -> None:
    """Delete a membership row, 404 if the user is not a member.

    Refuses to remove the current owner (409): ownership must be transferred
    first, so admin_id always points at a present member. This is the single
    chokepoint both surfaces call, so the rule is enforced once. Commits here
    (unlike the other mutations, which commit in the route body): both callers
    only read the household first for the 404 guard, so there is nothing
    unintended in the session to flush.
    """
    admin_id = await session.scalar(select(Household.admin_id).where(Household.id == household_id))
    if admin_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transfer ownership before removing the household admin",
        )
    result = await session.execute(
        delete(household_members).where(
            household_members.c.household_id == household_id,
            household_members.c.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Household member not found"
        )
    await session.commit()


# --- user endpoints (scoped to my active households) --------------------


async def _get_my_household_or_404(
    session: SessionDep, user_id: int, household_id: int
) -> Household:
    household = (
        await session.execute(
            select(Household).where(
                Household.id == household_id,
                member_of(user_id),
                Household.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if household is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Household not found")
    return household


async def _get_owned_household(session: SessionDep, user_id: int, household_id: int) -> Household:
    """A household the caller both belongs to (404 otherwise) and owns (403
    otherwise). Gates renaming, deleting and removing members - the things that stay the
    owner's alone. Managing *people* is one step wider, see `_get_organised_household`."""
    household = await _get_my_household_or_404(session, user_id, household_id)
    if household.admin_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the household admin can do this",
        )
    return household


async def _get_organised_household(
    session: SessionDep, user_id: int, household_id: int
) -> Household:
    """A household the caller belongs to (404 otherwise) and organises (403 otherwise).

    Gates inviting and role-setting, which the owner shares with the household's organisers:
    a house with several adults should not route every membership change through one person.
    The owner passes because owners are always organisers. What it does NOT cover is the
    narrower rule on *which* roles an organiser may set - that is caller-and-target specific,
    so it lives in `update_household_member`."""
    household = await _get_my_household_or_404(session, user_id, household_id)
    await require_role(session, household_id, user_id, HouseholdRole.organiser)
    return household


@router.get("", response_model=Page[HouseholdListRead])
async def list_households(
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: HouseholdSortBy = "created_at",
    sort_dir: SortDir = "desc",
    name: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[HouseholdListRead]:
    return await build_household_page(
        session,
        extra_filters=[member_of(user.id), Household.deleted_at.is_(None)],
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        name=name,
    )


@router.post("", response_model=HouseholdListRead, status_code=status.HTTP_201_CREATED)
async def create_household(
    payload: HouseholdCreate, user: CurrentUser, session: SessionDep
) -> HouseholdListRead:
    # The creator becomes the household owner and its first member, and owners are
    # organisers: there is nobody else who could promote them.
    household = Household(name=payload.name, admin_id=user.id, timezone=payload.timezone)
    session.add(household)
    await session.flush()
    await add_member(session, household.id, user.id, HouseholdRole.organiser)
    await session.commit()
    return await load_household_read(session, household.id)


@router.get("/{household_id}", response_model=HouseholdListRead)
async def get_household(
    household_id: int, user: CurrentUser, session: SessionDep
) -> HouseholdListRead:
    return await load_household_read(
        session,
        household_id,
        extra_filters=[member_of(user.id), Household.deleted_at.is_(None)],
    )


@router.patch("/{household_id}", response_model=HouseholdListRead)
async def update_household(
    household_id: int, payload: HouseholdUpdate, user: CurrentUser, session: SessionDep
) -> HouseholdListRead:
    household = await _get_owned_household(session, user.id, household_id)
    if payload.name is not None:
        household.name = payload.name
    if payload.admin_id is not None:
        await set_household_admin(session, household, payload.admin_id)
    rescheduled = await apply_timezone_change(session, household, payload.timezone)
    await commit_household_update(session, rescheduled=rescheduled)
    return await load_household_read(session, household.id)


@router.delete("/{household_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_household(household_id: int, user: CurrentUser, session: SessionDep) -> None:
    household = await _get_owned_household(session, user.id, household_id)
    # Soft delete: hide the household but leave its chores untouched.
    household.deleted_at = clock.now()
    await session.commit()


@router.get("/{household_id}/members", response_model=Page[HouseholdMemberRoleRead])
async def list_household_members(
    household_id: int,
    user: CurrentUser,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: MemberSortBy = "name",
    sort_dir: SortDir = "asc",
    name: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[HouseholdMemberRoleRead]:
    # Membership is enough to read the roster, roles included: everyone in a household
    # may see who else is in it and what they are allowed to do.
    await _get_my_household_or_404(session, user.id, household_id)
    return await build_members_page(
        session,
        household_id=household_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        name=name,
    )


@router.patch("/{household_id}/members/{user_id}", response_model=HouseholdMemberRoleRead)
async def update_household_member(
    household_id: int,
    user_id: int,
    payload: HouseholdMemberUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> HouseholdMemberRoleRead:
    """Set one member's role. The owner may set any of the three; an organiser may only move
    people between deputy and helper.

    That asymmetry is the point: an organiser can share the day-to-day load without being able
    to grow the set of people who could demote them. So they may not hand out `organiser`, may
    not touch a row that already holds it, and therefore may not demote themselves either -
    that last one falls out of the same rule rather than needing its own check.

    The checks are ordered deliberately. The owner's row is refused with a 409 **before** any
    caller-specific rule, because "the owner is always an organiser" is a property of the
    target: everyone gets the same actionable answer (transfer ownership, which promotes the
    new owner) instead of an organiser getting a 403 about a rule that is not the real reason.
    """
    household = await _get_organised_household(session, user.id, household_id)
    # Before the organiser rule, so an organiser targeting the owner hears about the target.
    refuse_owner_row(household, user_id)
    if household.admin_id != user.id:
        target_role = await role_in_household(session, household_id, user_id)
        if target_role == HouseholdRole.organiser or payload.role == HouseholdRole.organiser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the household admin can grant or change the organiser role",
            )
    return await set_member_role(session, household, user_id, payload.role)


@router.delete("/{household_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_household_member(
    household_id: int, user_id: int, user: CurrentUser, session: SessionDep
) -> None:
    await _get_owned_household(session, user.id, household_id)
    await remove_member(session, household_id, user_id)


@router.post("/{household_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_household(household_id: int, user: CurrentUser, session: SessionDep) -> None:
    # Any member may leave a household they belong to, except the owner: they
    # must transfer ownership first (enforced by remove_member's 409).
    await _get_my_household_or_404(session, user.id, household_id)
    await remove_member(session, household_id, user.id)


# --- invitations (owner and organisers) ---------------------------------


def _invitation_url(token: str) -> str:
    """The shareable invite link (points at the SPA, like the confirm link)."""
    return f"{settings.app_base_url.rstrip('/')}/invite?token={token}"


def _is_live_pending(invitation: HouseholdInvitation) -> bool:
    """A pending invite: the only revocable state (and the only one that counts
    toward the limit); every other state (accepted / revoked / expired) is
    deletable instead. Expiry is a stored status (flipped by the hourly sweep),
    so this trusts `status` rather than re-checking `expires_at`."""
    return invitation.status == HouseholdInvitationStatus.pending


def _invitation_read(invitation: HouseholdInvitation) -> HouseholdInvitationRead:
    return HouseholdInvitationRead(
        id=invitation.id,
        url=_invitation_url(invitation.token),
        status=HouseholdInvitationStatus(invitation.status),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


async def _get_invitation_or_404(
    session: SessionDep, household_id: int, invitation_id: int
) -> HouseholdInvitation:
    invitation = (
        await session.execute(
            select(HouseholdInvitation).where(
                HouseholdInvitation.id == invitation_id,
                HouseholdInvitation.household_id == household_id,
            )
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return invitation


@router.post(
    "/{household_id}/invitations",
    response_model=HouseholdInvitationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    household_id: int, user: CurrentUser, session: SessionDep
) -> HouseholdInvitationRead:
    await _get_organised_household(session, user.id, household_id)
    # Serialise this household's invite creation before counting. The cap is a read-decide-
    # write with no constraint behind it, so without the lock concurrent callers all read the
    # same count and all insert - and the overshoot is not bounded at one: measured on the dev
    # stack, 12 parallel POSTs against an empty household landed 11 invitations against a cap of
    # 5. That became reachable when inviting widened from the owner alone to every organiser,
    # since one person clicking one button does not race itself.
    #
    # Transaction-scoped, so it releases on the commit or rollback below with nothing to unwind,
    # and keyed on the household so two households never wait on each other. Cheap here: this
    # runs a handful of times per household, and only ever after `_get_organised_household` has
    # already established the caller belongs to it - so an unauthenticated request cannot reach
    # the lock at all.
    await session.execute(select(func.pg_advisory_xact_lock(household_id)))
    # Cap outstanding invites: only pending ones count (expired/accepted/revoked
    # don't). The hourly sweep keeps `status` current, so a stale pending row
    # only lingers in the count for up to the sweep interval.
    live_pending = await session.scalar(
        select(func.count())
        .select_from(HouseholdInvitation)
        .where(
            HouseholdInvitation.household_id == household_id,
            HouseholdInvitation.status == HouseholdInvitationStatus.pending,
        )
    )
    if (live_pending or 0) >= MAX_PENDING_INVITATIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            # "This household", not "you": any organiser can now invite, so the 5 pending
            # ones are as likely to be somebody else's, and this string is rendered verbatim.
            detail=(
                f"This household already has {MAX_PENDING_INVITATIONS} pending invitations; "
                "revoke one first."
            ),
        )
    invitation = HouseholdInvitation(
        token=generate_token(),
        household_id=household_id,
        invited_by=user.id,
        # Round the expiry up to the next whole hour so the sweep's :00 cadence
        # lands cleanly on it (lifetime is the TTL, at most an hour more).
        expires_at=round_up_to_hour(datetime.now(UTC) + INVITATION_TOKEN_TTL),
    )
    session.add(invitation)
    await session.commit()
    await session.refresh(invitation)
    return _invitation_read(invitation)


@router.get("/{household_id}/invitations", response_model=list[HouseholdInvitationRead])
async def list_invitations(
    household_id: int, user: CurrentUser, session: SessionDep
) -> list[HouseholdInvitationRead]:
    await _get_organised_household(session, user.id, household_id)
    # Newest first; accepted/revoked/expired invitations are kept until deleted.
    result = await session.execute(
        select(HouseholdInvitation)
        .where(HouseholdInvitation.household_id == household_id)
        .order_by(HouseholdInvitation.created_at.desc(), HouseholdInvitation.id.desc())
    )
    return [_invitation_read(invitation) for invitation in result.scalars()]


@router.post(
    "/{household_id}/invitations/{invitation_id}/revoke", response_model=HouseholdInvitationRead
)
async def revoke_invitation(
    household_id: int, invitation_id: int, user: CurrentUser, session: SessionDep
) -> HouseholdInvitationRead:
    await _get_organised_household(session, user.id, household_id)
    invitation = await _get_invitation_or_404(session, household_id, invitation_id)
    if not _is_live_pending(invitation):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a pending invitation can be revoked",
        )
    invitation.status = HouseholdInvitationStatus.revoked
    await session.commit()
    await session.refresh(invitation)
    return _invitation_read(invitation)


@router.delete(
    "/{household_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_invitation(
    household_id: int, invitation_id: int, user: CurrentUser, session: SessionDep
) -> None:
    await _get_organised_household(session, user.id, household_id)
    invitation = await _get_invitation_or_404(session, household_id, invitation_id)
    # A live pending invite must be revoked, not deleted; accepted / revoked /
    # expired ones are deletable.
    if _is_live_pending(invitation):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Revoke a pending invitation before deleting it",
        )
    await session.delete(invitation)
    await session.commit()
