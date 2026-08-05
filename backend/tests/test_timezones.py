"""Per-household timezones: the day boundary, DST, and what a zone change re-dates.

Split from `test_chores_core.py`, which pins the recurrence grid itself and passes UTC
throughout. Everything here is specifically about the zone mattering, so a case that would
read the same in UTC does not belong.

Two conventions worth knowing before adding to this file:

- **Endpoint cases pin the clock.** Day boundaries are the whole subject, and the interesting
  moment (01:30 in Amsterdam) is one that only exists for two hours a day. `app.core.clock.now`
  is the seam; monkeypatch the module attribute, never a name imported from it.
- **Extreme zones over plausible ones.** `Pacific/Kiritimati` (+14) and `Pacific/Niue` (-11)
  sit a day either side of UTC for most of the day, so a case built on them fails loudly if the
  zone is dropped somewhere. Europe/Amsterdam is used where the point is the reported bug or
  DST specifically.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.households import apply_timezone_change
from app.core import clock
from app.core.chores import (
    RecurrenceRule,
    days_late,
    days_since,
    days_until_due,
    first_occurrence,
    local_day_bounds,
    next_slot_after,
)
from app.core.households import household_zone
from app.core.occurrences import free_slot_from
from app.models import Chore, ChoreOccurrence, Household, OccurrenceStatus, RepeatPeriod, User

MakeUser = Callable[..., Awaitable[User]]
MakeHousehold = Callable[..., Awaitable[Household]]
MakeChore = Callable[..., Awaitable[Chore]]
MakeOccurrence = Callable[..., Awaitable[ChoreOccurrence]]
AuthClient = Callable[[User], Awaitable[AsyncClient]]

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
KIRITIMATI = ZoneInfo("Pacific/Kiritimati")  # UTC+14, always
NIUE = ZoneInfo("Pacific/Niue")  # UTC-11, always
# Springs forward at 24:00, so local midnight does not exist on the transition date.
SANTIAGO = ZoneInfo("America/Santiago")
UTC_ZONE = ZoneInfo("UTC")

DAILY = RecurrenceRule.of(RepeatPeriod.daily)
YEARLY = RecurrenceRule.of(RepeatPeriod.yearly)


def pin_clock(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """Freeze `clock.now()`. Patches the module attribute, which is the only thing that
    works: the endpoints call `clock.now()` rather than importing the name, precisely so
    this is possible."""
    monkeypatch.setattr(clock, "now", lambda: moment)


# --- first_occurrence: a start date becomes local midnight -------------------


def test_first_occurrence_anchors_at_local_midnight_not_utc() -> None:
    # 5 August 2026 in Amsterdam (CEST, UTC+2) begins at 22:00Z on the 4th. Storing midnight
    # UTC instead is what used to make the day boundary wrong.
    assert first_occurrence(date(2026, 8, 5), YEARLY, AMSTERDAM) == datetime(
        2026, 8, 4, 22, 0, tzinfo=UTC
    )


def test_first_occurrence_uses_the_winter_offset_for_a_winter_date() -> None:
    # CET (UTC+1) in January, so the same calendar date starts an hour later in absolute
    # terms. Nothing anywhere hardcodes "+2": the zone is asked per date.
    assert first_occurrence(date(2026, 1, 5), YEARLY, AMSTERDAM) == datetime(
        2026, 1, 4, 23, 0, tzinfo=UTC
    )


def test_first_occurrence_crosses_the_date_line_in_both_directions() -> None:
    # +14 means the local day starts a day and ten hours before the UTC one...
    assert first_occurrence(date(2026, 8, 5), YEARLY, KIRITIMATI) == datetime(
        2026, 8, 4, 10, 0, tzinfo=UTC
    )
    # ...and -11 means it starts eleven hours after. Between them these two straddle UTC, so
    # a dropped zone cannot pass both.
    assert first_occurrence(date(2026, 8, 5), YEARLY, NIUE) == datetime(
        2026, 8, 5, 11, 0, tzinfo=UTC
    )


def test_first_occurrence_in_utc_is_unchanged() -> None:
    # The old behaviour, still reachable: a UTC household gets midnight UTC. This is what
    # lets the rest of the suite keep its pre-timezone assertions.
    assert first_occurrence(date(2026, 8, 5), YEARLY, UTC_ZONE) == datetime(2026, 8, 5, tzinfo=UTC)


# --- DST: the grid holds local wall clock, not a fixed offset ----------------


def test_daily_slots_hold_local_midnight_across_the_spring_transition() -> None:
    # Amsterdam springs forward on Sunday 29 March 2026. A daily chore anchored at local
    # midnight must stay at local midnight, which means the *absolute* gap across the
    # transition is 23 hours, not 24. Stepping in UTC would leave it at 01:00 local forever.
    slot = first_occurrence(date(2026, 3, 28), DAILY, AMSTERDAM)
    for _ in range(4):
        slot = next_slot_after(slot, DAILY, AMSTERDAM)
        assert slot.astimezone(AMSTERDAM).hour == 0, slot
    # Four days on from Saturday the 28th, and still midnight local.
    assert slot.astimezone(AMSTERDAM).date() == date(2026, 4, 1)


def test_daily_slots_hold_local_midnight_across_the_autumn_transition() -> None:
    # The mirror: 25 October 2026 falls back, so that day is 25 hours long.
    slot = first_occurrence(date(2026, 10, 24), DAILY, AMSTERDAM)
    for _ in range(4):
        slot = next_slot_after(slot, DAILY, AMSTERDAM)
        assert slot.astimezone(AMSTERDAM).hour == 0, slot
    assert slot.astimezone(AMSTERDAM).date() == date(2026, 10, 28)


def test_the_transition_day_really_is_short() -> None:
    """Guards the two tests above from passing for the wrong reason. If the slots were plain
    midnight UTC every gap here would be a flat 24 hours and "hour == 0" would hold vacuously.

    Note the `.astimezone(UTC)` on both sides, which is not decoration: subtracting two aware
    datetimes that share a `tzinfo` ignores the zone entirely and subtracts the wall-clock
    fields, so `after - before` would be 24 hours whatever the offsets did. Converting first
    is what makes this measure elapsed time rather than calendar distance."""

    def elapsed(later: datetime, earlier: datetime) -> timedelta:
        return later.astimezone(UTC) - earlier.astimezone(UTC)

    before = first_occurrence(date(2026, 3, 28), DAILY, AMSTERDAM)
    after = next_slot_after(before, DAILY, AMSTERDAM)
    assert elapsed(after, before) == timedelta(hours=24)  # 28 -> 29 Mar, both still CET
    across = next_slot_after(after, DAILY, AMSTERDAM)
    assert elapsed(across, after) == timedelta(hours=23)  # 29 -> 30 Mar, the clocks went forward


def test_weekday_pinning_reads_the_local_weekday() -> None:
    # Sunday 2 August 2026 at 22:00Z is already Monday the 3rd in Amsterdam, so a chore
    # pinned to Mondays is on its day and must not be pushed a week out.
    mondays = RecurrenceRule.of(RepeatPeriod.weekly, 1, [0])
    slot = first_occurrence(date(2026, 8, 3), mondays, AMSTERDAM)
    assert slot == datetime(2026, 8, 2, 22, 0, tzinfo=UTC)
    assert slot.astimezone(AMSTERDAM).date() == date(2026, 8, 3)


# --- The day helpers --------------------------------------------------------


def test_days_until_due_is_the_reported_bug() -> None:
    # 01:30 on 5 August in Amsterdam is 23:30 on the 4th in UTC. The chore due on the 5th
    # must read as due today; against a UTC day it read as due tomorrow, which is the bug
    # this whole feature exists for.
    now = datetime(2026, 8, 4, 23, 30, tzinfo=UTC)
    due = first_occurrence(date(2026, 8, 5), YEARLY, AMSTERDAM)
    assert days_until_due(due, now, AMSTERDAM) == 0
    # The old world, pinned so the assertion above means something: the slot stored at
    # midnight UTC (what the migration re-anchored away from), judged against a UTC day.
    # It reads as due tomorrow, which is exactly what the user saw at 01:30.
    old_slot = datetime(2026, 8, 5, tzinfo=UTC)
    assert days_until_due(old_slot, now, UTC_ZONE) == 1


def test_days_since_counts_local_days() -> None:
    # Done at 00:30 local on the 5th (22:30Z on the 4th); at 09:00 local the same day that
    # is "earlier today", not yesterday.
    completed = datetime(2026, 8, 4, 22, 30, tzinfo=UTC)
    now = datetime(2026, 8, 5, 7, 0, tzinfo=UTC)  # 09:00 in Amsterdam
    assert days_since(completed, now, AMSTERDAM) == 0
    assert days_since(completed, now, UTC_ZONE) == 1


def test_days_late_forgives_a_late_evening_completion() -> None:
    # Due on the 5th, ticked off at 23:00 local on the 5th (21:00Z). On time locally; a day
    # late if the day boundary is UTC.
    due = first_occurrence(date(2026, 8, 5), YEARLY, AMSTERDAM)
    completed = datetime(2026, 8, 5, 21, 0, tzinfo=UTC)
    assert days_late(due, completed, AMSTERDAM) == 0
    assert days_late(due, completed, UTC_ZONE) == 1


def test_local_day_bounds_are_a_local_day_long() -> None:
    start, end = local_day_bounds(datetime(2026, 8, 5, 12, 0, tzinfo=UTC), AMSTERDAM)
    assert start == datetime(2026, 8, 4, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 8, 5, 22, 0, tzinfo=UTC)


def test_local_day_bounds_stretch_across_a_dst_transition() -> None:
    # 25 October 2026 is 25 hours long in Amsterdam. A fixed 24-hour window would drop the
    # last hour of the day out of "today". Converted to UTC before subtracting - see
    # `test_the_transition_day_really_is_short` for why a same-zone subtraction cannot see it.
    start, end = local_day_bounds(datetime(2026, 10, 25, 12, 0, tzinfo=UTC), AMSTERDAM)
    assert end.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=25)


async def test_free_slot_from_sees_a_taken_slot_at_a_nonexistent_local_midnight(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    db_session: AsyncSession,
) -> None:
    """A gap-local candidate must still find a done row at the same instant.

    `America/Santiago` springs forward at 24:00, so local midnight on 6 September 2026 does not
    exist. Python resolves it under `fold=0` to a real instant - but inter-zone `==` is not
    reflexive for a time in a gap (PEP 495), so the household-zone candidate compared *unequal*
    to the identical UTC instant Postgres returns, while hashing to the same bucket. The set
    lookup therefore reported an occupied slot as free and handed back the unclearable 409
    `free_slot_from` exists to prevent.

    Revert the `.astimezone(UTC)` in the membership test and this returns the collision instead
    of stepping past it.
    """
    user = await make_user()
    household = await make_household(members=[user], timezone="America/Santiago")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 9, 6),
        repeats=RepeatPeriod.daily,
        with_occurrence=False,
    )
    candidate = first_occurrence(date(2026, 9, 6), DAILY, SANTIAGO)
    # The slot is occupied by a completed row at exactly that instant.
    await make_occurrence(
        chore=chore,
        scheduled_for=candidate,
        status=OccurrenceStatus.done,
        completed_at=candidate,
        completed_by=user,
    )

    slot = await free_slot_from(db_session, chore.id, candidate, DAILY, SANTIAGO)

    assert slot.astimezone(UTC) != candidate.astimezone(UTC), "walked past nothing"
    assert slot.astimezone(SANTIAGO).date() == date(2026, 9, 7)


# --- the two implementations of one transform -------------------------------


async def test_the_sql_and_python_reanchor_transforms_agree(db_session: AsyncSession) -> None:
    """The timezone migration re-anchors slots in SQL (`AT TIME ZONE` twice) and
    `reanchor_open_occurrences` does the same thing in Python. Two implementations of one rule,
    in two languages, with two tz databases behind them - the pair in this change most likely to
    drift, and nothing else compares them (pytest never executes a migration).

    Both express "read this instant's wall clock in one zone, then call that reading local to
    another". The migration's `from` zone is always UTC; the runtime's is whatever the household
    was in, so UTC is just the case they share.

    The cases are the ones that could disagree: either side of both DST transitions in a zone
    that has them, the date line in both directions, a half-hour offset, and a zone whose
    transition is at midnight (`America/Santiago`), where local midnight does not exist on the
    spring date and Python resolves it under `fold=0`.
    """
    moments = [
        datetime(2026, 8, 5, tzinfo=UTC),  # summer
        datetime(2026, 1, 5, tzinfo=UTC),  # winter
        datetime(2026, 3, 29, tzinfo=UTC),  # EU spring-forward date
        datetime(2026, 10, 25, tzinfo=UTC),  # EU fall-back date
        datetime(2026, 9, 6, tzinfo=UTC),  # Santiago springs forward at 24:00
        datetime(2026, 8, 5, 13, 45, tzinfo=UTC),  # a non-midnight slot (ex-`manual` chore)
    ]
    zones = [
        "Europe/Amsterdam",
        "Pacific/Kiritimati",
        "Pacific/Niue",
        "Asia/Kathmandu",  # +05:45
        "America/Santiago",
        "UTC",
    ]
    for zone in zones:
        for moment in moments:
            sql = await db_session.scalar(
                text("SELECT (:ts AT TIME ZONE 'UTC') AT TIME ZONE :zone").bindparams(
                    ts=moment, zone=zone
                )
            )
            python = moment.astimezone(UTC).replace(tzinfo=ZoneInfo(zone))
            # Both sides normalised to UTC before comparing, which is load-bearing rather than
            # tidiness: inter-zone `==` is not reflexive for a local time inside a DST gap
            # (PEP 495), so the `America/Santiago` case below compares unequal to its own
            # instant if you skip this. That is the same trap `free_slot_from`'s set membership
            # had to be fixed for, and the reason this case is in the list at all.
            assert sql == python.astimezone(UTC), (
                f"{zone} at {moment.isoformat()}: SQL {sql} != Python {python}"
            )


# --- household_zone ---------------------------------------------------------


def test_household_zone_falls_back_to_utc_on_an_unknown_name() -> None:
    # Unreachable through the API (the schema validates on write), so this is about a hand
    # edited row or a zone the tz database dropped. Degrading to the old app-wide behaviour
    # beats raising on every read path the household appears on.
    assert household_zone("Mars/Olympus_Mons") == UTC_ZONE
    assert household_zone("Europe/Amsterdam") == AMSTERDAM


# --- The Home endpoint, with the clock pinned -------------------------------


async def test_home_shows_todays_chore_at_half_past_one_in_the_morning(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reported bug, end to end: at 01:30 Amsterdam the chore due that day reads as due
    today rather than tomorrow, and yesterday's reads as overdue rather than due today."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    await make_chore(
        household=household, title="Today", start_date=date(2026, 8, 5), repeats=RepeatPeriod.yearly
    )
    await make_chore(
        household=household,
        title="Yesterday",
        start_date=date(2026, 8, 4),
        repeats=RepeatPeriod.yearly,
    )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 4, 23, 30, tzinfo=UTC))  # 01:30 on the 5th, local

    body = (await client.get("/api/v1/home")).json()
    assert {i["title"]: i["days_until_due"] for i in body["items"]} == {"Today": 0, "Yesterday": -1}
    assert {i["title"]: i["status"] for i in body["items"]} == {
        "Today": "today",
        "Yesterday": "overdue",
    }


async def test_home_uses_the_household_day_late_in_the_evening(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case that actually pins the endpoint's *comparison* zone, as opposed to the
    anchoring of its slots.

    The 01:30 test above passes even with the comparison reverted to UTC, because the slot and
    the clock are both shifted by the same two hours and the difference between two dates
    survives that. Only a moment where exactly one of them crosses midnight discriminates.
    23:00 local on the 4th (21:00Z) is one: locally the chore due on the 5th is due
    *tomorrow*, while in UTC both fall on the 4th and it reads as due today.

    Verified by mutation - revert `days_until_due`'s zone in `home.py` and this fails while
    the one above does not.
    """
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    await make_chore(
        household=household,
        title="Tomorrow",
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
    )
    await make_chore(
        household=household, title="Today", start_date=date(2026, 8, 4), repeats=RepeatPeriod.yearly
    )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 4, 21, 0, tzinfo=UTC))  # 23:00 on the 4th, local

    body = (await client.get("/api/v1/home")).json()
    # In UTC these would be 0 and -1 respectively - a chore claiming to be due today when the
    # household still has a whole hour of the previous day left.
    assert {i["title"]: i["days_until_due"] for i in body["items"]} == {"Tomorrow": 1, "Today": 0}


async def test_home_judges_each_household_against_its_own_day(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Home spans every household in one query, so the day window cannot be global.

    10:30Z is the narrow hour that separates all three: +14 has just crossed into the 6th,
    -11 is still on the 4th, and UTC is on the 5th. Any earlier and Kiritimati agrees with
    UTC; any later and Niue does. So the same calendar start date has to land in three
    different buckets, which no single global day boundary can produce."""
    user = await make_user()
    east = await make_household(name="East", members=[user], timezone="Pacific/Kiritimati")
    west = await make_household(name="West", members=[user], timezone="Pacific/Niue")
    neutral = await make_household(name="Neutral", members=[user], timezone="UTC")
    for household, title in ((east, "East"), (west, "West"), (neutral, "Neutral")):
        await make_chore(
            household=household,
            title=title,
            start_date=date(2026, 8, 5),
            repeats=RepeatPeriod.yearly,
        )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 5, 10, 30, tzinfo=UTC))

    body = (await client.get("/api/v1/home")).json()
    assert {i["title"]: i["days_until_due"] for i in body["items"]} == {
        "East": -1,  # 00:30 on the 6th there, so the 5th is behind them
        "Neutral": 0,
        "West": 1,  # 23:30 on the 4th there, so the 5th is tomorrow
    }


async def test_home_carries_the_household_timezone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
) -> None:
    # The frontend renders `next_due` in this zone so the date it prints agrees with the
    # server-computed "Due today" beside it.
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    await make_chore(household=household, repeats=RepeatPeriod.yearly)
    client = await auth_client(user)

    body = (await client.get("/api/v1/home")).json()
    assert body["items"][0]["household"]["timezone"] == "Europe/Amsterdam"


async def test_todays_progress_uses_the_household_day(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The progress bar's "done today" window is per household too. A completion at 23:30Z
    on the 4th is 01:30 on the 5th locally, so at 02:00 local it still counts as today."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    # `with_occurrence=False`: the fixture would otherwise open a row on this very slot, and
    # uq_occurrence_chore_scheduled is per (chore, scheduled_for).
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
        with_occurrence=False,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=first_occurrence(date(2026, 8, 5), YEARLY, AMSTERDAM),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 8, 4, 23, 30, tzinfo=UTC),
        completed_by=user,
    )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 5, 0, 0, tzinfo=UTC))  # 02:00 on the 5th, local

    body = (await client.get("/api/v1/home")).json()
    assert body["progress"]["done_today"] == 1


# --- Creating and changing a household's zone -------------------------------


async def test_create_household_requires_a_known_timezone(
    make_user: MakeUser, auth_client: AuthClient
) -> None:
    user = await make_user()
    client = await auth_client(user)

    assert (await client.post("/api/v1/households", json={"name": "No zone"})).status_code == 422
    bad = await client.post(
        "/api/v1/households", json={"name": "Bad zone", "timezone": "Mars/Olympus_Mons"}
    )
    assert bad.status_code == 422
    good = await client.post(
        "/api/v1/households", json={"name": "Good", "timezone": "Europe/Amsterdam"}
    )
    assert good.status_code == 201
    assert good.json()["timezone"] == "Europe/Amsterdam"


async def test_chores_created_in_a_household_use_its_zone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    client = await auth_client(user)

    resp = await client.post(
        "/api/v1/chores",
        json={
            "household_id": household.id,
            "title": "Bins",
            "start_date": "2026-08-05",
            "repeats": "yearly",
            "assignment_type": "manual",
        },
    )
    assert resp.status_code == 201
    slot = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == resp.json()["id"],
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert slot == datetime(2026, 8, 4, 22, 0, tzinfo=UTC)


async def test_changing_the_timezone_keeps_open_chores_on_their_local_date(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Moving a household re-anchors its open slots so "due 5 August" still says 5 August.
    Leaving them alone would silently shift every scheduled chore by a day."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household, start_date=date(2026, 8, 5), repeats=RepeatPeriod.yearly
    )
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"}
    )
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "Pacific/Niue"

    slot = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert slot == datetime(2026, 8, 5, 11, 0, tzinfo=UTC)  # local midnight on the 5th in Niue
    assert slot.astimezone(NIUE).date() == date(2026, 8, 5)


async def test_the_admin_surface_re_anchors_too(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Both PATCH handlers call the same helper, but the whole point of sharing it is that
    neither surface can silently skip the re-anchor - so drive the admin one end to end. A
    household whose zone moved from Admin > Households and did not re-date would leave chores a
    day off depending on which page the change was made from."""
    admin = await make_user(email="admin@example.com", is_admin=True)
    household = await make_household(members=[admin], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household, start_date=date(2026, 8, 5), repeats=RepeatPeriod.yearly
    )
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/households/{household.id}", json={"timezone": "Pacific/Niue"}
    )
    assert resp.status_code == 200
    slot = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert slot == datetime(2026, 8, 5, 11, 0, tzinfo=UTC)  # local midnight on the 5th in Niue


async def test_the_admin_surface_rejects_an_unknown_timezone(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    admin = await make_user(email="admin@example.com", is_admin=True)
    household = await make_household(members=[admin])
    client = await auth_client(admin)

    resp = await client.patch(
        f"/api/v1/admin/households/{household.id}", json={"timezone": "Mars/Olympus_Mons"}
    )
    assert resp.status_code == 422


async def test_changing_the_timezone_leaves_history_alone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Done rows record when things actually happened, so a decision made afterwards must
    not rewrite them - `completed_at` least of all."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
        with_occurrence=False,
    )
    done_slot = datetime(2026, 7, 4, 22, 0, tzinfo=UTC)
    completed = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)
    await make_occurrence(
        chore=chore,
        scheduled_for=done_slot,
        status=OccurrenceStatus.done,
        completed_at=completed,
        completed_by=user,
    )
    client = await auth_client(user)

    await client.patch(f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"})

    row = await db_session.scalar(
        select(ChoreOccurrence).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.done,
        )
    )
    assert row is not None
    assert row.scheduled_for == done_slot
    assert row.completed_at == completed


async def test_changing_the_timezone_leaves_unscheduled_chores_alone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """An unscheduled chore's slot is the moment it became available, not a calendar
    anchor, so it is already a correct instant and re-anchoring would corrupt
    `days_since_last_completion`."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    before = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(ChoreOccurrence.chore_id == chore.id)
    )
    client = await auth_client(user)

    await client.patch(f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"})

    after = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(ChoreOccurrence.chore_id == chore.id)
    )
    assert after == before


async def test_statistics_bucket_each_completion_in_its_own_households_day(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Statistics spans every household the caller is a deputy in, so its range window and its
    day buckets are per household just like Home's.

    One instant, 2026-08-04T22:30Z, closed in two households: 00:30 on the 5th in Amsterdam and
    11:30 on the 4th in Niue. They must land in different buckets. Judged in a single zone they
    would collapse into one, which is what makes this fail if `zone_by_household` is dropped."""
    user = await make_user()
    east = await make_household(name="East", members=[user], timezone="Europe/Amsterdam")
    west = await make_household(name="West", members=[user], timezone="Pacific/Niue")
    moment = datetime(2026, 8, 4, 22, 30, tzinfo=UTC)
    for household, tz in ((east, AMSTERDAM), (west, NIUE)):
        chore = await make_chore(
            household=household,
            start_date=date(2026, 8, 1),
            repeats=RepeatPeriod.yearly,
            with_occurrence=False,
        )
        await make_occurrence(
            chore=chore,
            scheduled_for=first_occurrence(date(2026, 8, 1), YEARLY, tz),
            status=OccurrenceStatus.done,
            completed_at=moment,
            completed_by=user,
        )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 5, 10, 0, tzinfo=UTC))

    body = (await client.get("/api/v1/stats?range=7d")).json()
    counted = {b["bucket"]: b["count"] for b in body["completions_over_time"] if b["count"]}
    assert counted == {"2026-08-04": 1, "2026-08-05": 1}
    assert body["kpis"]["completed_in_range"] == 2


async def test_statistics_punctuality_uses_the_household_day(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`days_late` inside the punctuality tally needs the zone too: due on the 5th and ticked
    off at 23:00 local on the 5th is on time locally and a day late in UTC."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
        with_occurrence=False,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=first_occurrence(date(2026, 8, 5), YEARLY, AMSTERDAM),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 8, 5, 21, 0, tzinfo=UTC),  # 23:00 local, same day
        completed_by=user,
    )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 6, 10, 0, tzinfo=UTC))

    body = (await client.get("/api/v1/stats?range=7d")).json()
    assert body["punctuality"]["on_time"] == 1
    assert body["punctuality"]["late"] == 0


async def test_statistics_live_snapshot_uses_the_household_day(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The open-occurrence snapshot selects `Chore.household_id` purely so each slot can be
    judged against its own household's day. Same 10:30Z moment Home's multi-zone case uses:
    the 5th is behind Kiritimati, today in UTC and tomorrow in Niue."""
    user = await make_user()
    for name, tz in (("East", "Pacific/Kiritimati"), ("Mid", "UTC"), ("West", "Pacific/Niue")):
        household = await make_household(name=name, members=[user], timezone=tz)
        await make_chore(
            household=household,
            title=name,
            start_date=date(2026, 8, 5),
            repeats=RepeatPeriod.yearly,
        )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 5, 10, 30, tzinfo=UTC))

    breakdown = (await client.get("/api/v1/stats?range=7d")).json()["status_breakdown"]
    assert breakdown == {"overdue": 1, "today": 1, "soon": 1}


async def test_unscheduled_counts_days_in_the_household_zone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Done at 00:30 local on the 5th; at 09:00 local the same day that is "earlier today"."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(household=household, repeats=RepeatPeriod.manual)
    await make_occurrence(
        chore=chore,
        scheduled_for=datetime(2026, 8, 1, tzinfo=UTC),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 8, 4, 22, 30, tzinfo=UTC),
        completed_by=user,
    )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 5, 7, 0, tzinfo=UTC))  # 09:00 local

    body = (await client.get("/api/v1/unscheduled")).json()
    # 1 in UTC, where the completion falls on the 4th and "now" on the 5th.
    assert body["items"][0]["days_since_last_completion"] == 0


async def test_history_lateness_uses_the_household_zone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """Due on the 5th, ticked off at 23:00 local on the 5th: on time, not a day late."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
        with_occurrence=False,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=first_occurrence(date(2026, 8, 5), YEARLY, AMSTERDAM),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 8, 5, 21, 0, tzinfo=UTC),
        completed_by=user,
    )
    client = await auth_client(user)

    body = (await client.get("/api/v1/completions")).json()
    assert body["items"][0]["days_late"] == 0
    assert body["items"][0]["household"]["timezone"] == "Europe/Amsterdam"


async def test_patch_rejects_an_unknown_timezone(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    """`HouseholdUpdate.timezone` is `Timezone | None`, a different annotation from the create
    schema's, so it is its own validator path and needs its own negative case."""
    user = await make_user()
    household = await make_household(members=[user], admin=user)
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/households/{household.id}", json={"timezone": "Mars/Olympus_Mons"}
    )
    assert resp.status_code == 422
    # And the household is untouched.
    assert (await client.get(f"/api/v1/households/{household.id}")).json()["timezone"] == "UTC"


async def test_apply_timezone_change_skips_the_work_when_the_zone_did_not_move(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
) -> None:
    """The two guards in `apply_timezone_change`, pinned on its return value.

    Asserting through the endpoint does not work, and the obvious version of this test is a
    trap: re-anchoring an unchanged zone produces the same *instant* each row already holds,
    aware datetimes compare by instant, and SQLAlchemy emits no UPDATE for an equal-value set -
    so nothing is written and `updated_at` does not move whether the guard is there or not.
    What the guards actually save is the query per open occurrence that `free_slot_from` costs,
    and the count returned here is the only observable difference: without them the unchanged
    and omitted cases would report 1 (the work they did) instead of 0.
    """
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    await make_chore(household=household, start_date=date(2026, 8, 5), repeats=RepeatPeriod.yearly)
    await db_session.refresh(household)

    assert await apply_timezone_change(db_session, household, None) == 0
    assert await apply_timezone_change(db_session, household, "Europe/Amsterdam") == 0
    # ...and a real move does the work, so the zeroes above are a decision rather than a
    # function that never does anything.
    assert await apply_timezone_change(db_session, household, "Pacific/Niue") == 1


async def test_a_zone_change_cannot_land_on_an_already_completed_slot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """`uq_occurrence_chore_scheduled` is per (chore, scheduled_for), so a re-anchored slot
    landing on a done row would 409 the whole PATCH. `free_slot_from` walks it past."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.daily,
        with_occurrence=False,
    )
    # The slot the open row is about to be re-anchored onto: local midnight on the 5th in
    # Niue. Pre-occupy it with a completed row.
    collision = datetime(2026, 8, 5, 11, 0, tzinfo=UTC)
    await make_occurrence(
        chore=chore,
        scheduled_for=collision,
        status=OccurrenceStatus.done,
        completed_at=collision,
        completed_by=user,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=first_occurrence(date(2026, 8, 5), DAILY, AMSTERDAM),
        status=OccurrenceStatus.open,
    )
    client = await auth_client(user)

    resp = await client.patch(
        f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"}
    )
    assert resp.status_code == 200
    slot = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    # Stepped one day on rather than colliding, and still local midnight.
    assert slot == datetime(2026, 8, 6, 11, 0, tzinfo=UTC)


# --- chore_occurrences.updated_at -------------------------------------------


async def test_occurrence_updated_at_starts_equal_to_created_at(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
) -> None:
    user = await make_user()
    household = await make_household(members=[user])
    chore = await make_chore(household=household)
    occ = await db_session.scalar(
        select(ChoreOccurrence).where(ChoreOccurrence.chore_id == chore.id)
    )
    assert occ is not None
    assert occ.updated_at == occ.created_at


def test_occurrence_updated_at_is_stamped_on_every_write() -> None:
    """That `updated_at` actually *moves* cannot be asserted end to end here.

    Both defaults are SQL `now()`, which in Postgres is `transaction_timestamp()` - frozen for
    the whole transaction. In production each request is its own transaction, so a completion
    genuinely stamps a later value; under the savepoint fixtures the entire test shares one
    outer transaction, so `created_at` and `updated_at` come back identical no matter how many
    updates ran in between. The same limitation the boot migration and the advisory lock have.

    So this pins the configuration instead - the thing that would actually be lost if someone
    dropped the `onupdate` - and the elapsed behaviour is a by-hand check (complete a chore in
    the dev stack, then compare the two columns). Note the `is not None`: a plain truthiness
    check would pass on a column with no onupdate at all, since SQLAlchemy stores None there.
    """
    column = ChoreOccurrence.__table__.c.updated_at
    assert column.onupdate is not None
    assert column.server_default is not None
    assert not column.nullable
