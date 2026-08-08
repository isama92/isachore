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
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.chores import (
    _close_occurrence,
    _get_user_chore_or_404,
    _open_occurrence,
)
from app.api.v1.households import apply_timezone_change
from app.core import clock
from app.core.chores import (
    RecurrenceRule,
    days_late,
    days_since,
    days_until_due,
    end_of_local_day,
    first_occurrence,
    local_day_bounds,
    next_slot_after,
)
from app.core.households import household_zone
from app.core.occurrences import closure_zone, free_slot_from
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


def test_end_of_local_day_is_the_households_midnight_not_utcs() -> None:
    # What a completion recorded on its due day is dated with. Both extremes in one case, so
    # a dropped zone cannot pass: they straddle UTC, and the UTC answers (23:59:59.999999 on
    # the 5th and the 6th respectively) match neither.
    kiritimati_slot = first_occurrence(date(2026, 8, 6), DAILY, KIRITIMATI)
    assert end_of_local_day(kiritimati_slot, KIRITIMATI) == datetime(
        2026, 8, 6, 9, 59, 59, 999999, tzinfo=UTC
    )
    niue_slot = first_occurrence(date(2026, 8, 6), DAILY, NIUE)
    assert end_of_local_day(niue_slot, NIUE) == datetime(2026, 8, 7, 10, 59, 59, 999999, tzinfo=UTC)
    # Still the day the chore was due, in both, which is the property the whole thing rests on.
    assert end_of_local_day(kiritimati_slot, KIRITIMATI).astimezone(KIRITIMATI).date() == date(
        2026, 8, 6
    )
    assert end_of_local_day(niue_slot, NIUE).astimezone(NIUE).date() == date(2026, 8, 6)


def test_end_of_local_day_survives_a_zone_whose_midnight_does_not_exist() -> None:
    # Santiago springs forward at 24:00, so 6 September 2026 has no local midnight and the
    # 5th ends at 04:00Z on the 6th. Deriving from `local_day_bounds` is what gets this right
    # for free; hand-building 23:59:59 would land an hour out, on the wrong side of the gap.
    slot = first_occurrence(date(2026, 9, 5), DAILY, SANTIAGO)
    assert end_of_local_day(slot, SANTIAGO) == datetime(2026, 9, 6, 3, 59, 59, 999999, tzinfo=UTC)
    assert end_of_local_day(slot, SANTIAGO).astimezone(SANTIAGO).date() == date(2026, 9, 5)


def test_the_end_of_a_fall_back_day_is_25_hours_on() -> None:
    # The mirror of test_local_day_bounds_stretch_across_a_dst_transition, for the instant
    # actually used. `.astimezone(UTC)` on both sides is not decoration: two aware datetimes
    # sharing a tzinfo subtract wall-clock fields, so this reads a flat 24 hours without it.
    slot = first_occurrence(date(2026, 10, 25), DAILY, AMSTERDAM)
    elapsed = end_of_local_day(slot, AMSTERDAM).astimezone(UTC) - slot.astimezone(UTC)
    assert elapsed == timedelta(hours=25) - timedelta(microseconds=1)


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


async def test_a_zone_that_is_not_a_place_is_refused(
    make_user: MakeUser, make_household: MakeHousehold, auth_client: AuthClient
) -> None:
    """`available_timezones()` is a superset of what a browser can format with - 599 names against
    `Intl.supportedValuesOf`'s 418 here - and two of the extras are not places at all.
    `new Intl.DateTimeFormat('en-GB', {timeZone: 'localtime'})` throws `RangeError`, as does
    `Factory`, so storing either put a value in the database that every page rendering a household
    timestamp would crash on.

    The frontend degrades an unformattable zone rather than throwing (`renderableZone`), so this
    is about keeping the stored value honest rather than about the crash. `localtime` is wrong on
    its own terms too: it resolves to the *container's* zone, so it would move with a base-image
    bump.
    """
    user = await make_user()
    household = await make_household(members=[user], admin=user)
    client = await auth_client(user)

    for bad in ("localtime", "Factory"):
        created = await client.post("/api/v1/households", json={"name": "X", "timezone": bad})
        assert created.status_code == 422, bad
        patched = await client.patch(f"/api/v1/households/{household.id}", json={"timezone": bad})
        assert patched.status_code == 422, bad
    # A real place with the same shape still goes through, so this is a two-name exclusion rather
    # than a narrower allowlist.
    assert (
        await client.patch(f"/api/v1/households/{household.id}", json={"timezone": "Asia/Tokyo"})
    ).status_code == 200


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


async def test_lateness_survives_a_move_because_the_closure_snapshots_its_zone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
) -> None:
    """The whole reason `completed_timezone` exists.

    Due 5 July, ticked off at 23:00 local on the day: on time. Read against the household's
    *current* zone that becomes "1 day late" the moment the household moves west, silently
    re-scoring History's badge, `punctuality` and `on_time_rate` for work nobody touched.
    Judged in the snapshot it does not move.
    """
    user = await make_user()
    household = await make_household(members=[user], admin=user, timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 7, 5),
        repeats=RepeatPeriod.yearly,
        with_occurrence=False,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=first_occurrence(date(2026, 7, 5), YEARLY, AMSTERDAM),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 7, 5, 21, 0, tzinfo=UTC),  # 23:00 local, same day
        completed_timezone="Europe/Amsterdam",
        completed_by=user,
    )
    client = await auth_client(user)

    assert (await client.get("/api/v1/completions")).json()["items"][0]["days_late"] == 0

    resp = await client.patch(
        f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"}
    )
    assert resp.status_code == 200

    # Still 0. Without the snapshot this reads 1.
    row = (await client.get("/api/v1/completions")).json()["items"][0]
    assert row["days_late"] == 0
    # And the snapshot is on the wire, still naming where the closure happened rather than where
    # the household now is - which is what lets the client render `completed_at` in the same zone
    # `days_late` was computed in. Rendered in the household's current zone instead, this row
    # would show a completion date that contradicts its own lateness badge.
    assert row["completed_timezone"] == "Europe/Amsterdam"
    assert row["household"]["timezone"] == "Pacific/Niue"


async def test_a_stats_bucket_survives_a_move_for_the_same_reason(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    make_occurrence: MakeOccurrence,
    auth_client: AuthClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Which local day a completion is counted on is the same kind of judgement as its lateness,
    so it reads the same snapshot. A completion at 22:30Z on the 4th is the 5th in Amsterdam and
    the 4th in Niue; after a move it must stay on the 5th."""
    user = await make_user()
    household = await make_household(members=[user], admin=user, timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 1),
        repeats=RepeatPeriod.yearly,
        with_occurrence=False,
    )
    await make_occurrence(
        chore=chore,
        scheduled_for=first_occurrence(date(2026, 8, 1), YEARLY, AMSTERDAM),
        status=OccurrenceStatus.done,
        completed_at=datetime(2026, 8, 4, 22, 30, tzinfo=UTC),
        completed_timezone="Europe/Amsterdam",
        completed_by=user,
    )
    client = await auth_client(user)
    pin_clock(monkeypatch, datetime(2026, 8, 5, 10, 0, tzinfo=UTC))

    def counted(body: dict) -> dict[str, int]:
        return {b["bucket"]: b["count"] for b in body["completions_over_time"] if b["count"]}

    assert counted((await client.get("/api/v1/stats?range=7d")).json()) == {"2026-08-05": 1}

    await client.patch(f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"})

    # Still the 5th. Without the snapshot it re-buckets to the 4th.
    assert counted((await client.get("/api/v1/stats?range=7d")).json()) == {"2026-08-05": 1}


async def test_completing_and_skipping_stamp_the_household_zone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """Both closure paths go through `_close_occurrence`, so both must stamp it."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Pacific/Kiritimati")
    completed = await make_chore(household=household, title="Done one", assignees=[user])
    skipped = await make_chore(household=household, title="Skipped one", assignees=[user])
    client = await auth_client(user)

    assert (
        await client.post(f"/api/v1/chores/{completed.id}/complete", json={})
    ).status_code == 201
    assert (await client.post(f"/api/v1/chores/{skipped.id}/skip", json={})).status_code == 201

    zones = (
        (
            await db_session.execute(
                select(ChoreOccurrence.completed_timezone).where(
                    ChoreOccurrence.status == OccurrenceStatus.done
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(zones) == {"Pacific/Kiritimati"}


async def test_undoing_a_completion_clears_the_snapshot(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The row is open again, so there is no closure for a zone to have judged. Leaving it would
    hand the next completion of this slot a zone from whenever the previous one happened."""
    user = await make_user()
    household = await make_household(members=[user], admin=user, timezone="Pacific/Kiritimati")
    chore = await make_chore(household=household, assignees=[user])
    client = await auth_client(user)
    completion = (await client.post(f"/api/v1/chores/{chore.id}/complete", json={})).json()

    assert (await client.delete(f"/api/v1/completions/{completion['id']}")).status_code == 204

    reopened = await db_session.scalar(
        select(ChoreOccurrence).where(ChoreOccurrence.id == completion["id"])
    )
    assert reopened is not None
    assert reopened.status == OccurrenceStatus.open
    assert reopened.completed_timezone is None


def test_closure_zone_falls_back_to_the_household_for_a_pre_column_closure() -> None:
    """NULL means "not judged yet" (any open row) or "closed before the column existed". The
    fallback is the household's current zone, which is both the old behaviour and all the
    migration's backfill can honestly reconstruct."""
    assert closure_zone(None, "Europe/Amsterdam") == AMSTERDAM
    assert closure_zone("Pacific/Niue", "Europe/Amsterdam") == NIUE
    # And a snapshot the tz database no longer knows degrades the same way any stored zone does.
    assert closure_zone("Mars/Olympus_Mons", "Europe/Amsterdam") == UTC_ZONE


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


async def test_changing_the_timezone_leaves_soft_deleted_chores_alone(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
) -> None:
    """The third of `reanchor_open_occurrences`' documented exclusions, and the one that had no
    test - so deleting `Chore.deleted_at.is_(None)` from its query broke nothing.

    Nothing shows a soft-deleted chore and nothing can complete it, so re-anchoring its slot is
    work with no observer. It also matters for the count the caller gates its 409 on: a household
    full of deleted chores would report a re-scheduling that nobody could see.
    """
    user = await make_user()
    household = await make_household(members=[user], admin=user, timezone="Europe/Amsterdam")
    live = await make_chore(
        household=household,
        title="Live",
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
    )
    deleted = await make_chore(
        household=household,
        title="Deleted",
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.yearly,
    )
    client = await auth_client(user)
    assert (await client.delete(f"/api/v1/chores/{deleted.id}")).status_code == 204

    async def slot_of(chore_id: int) -> datetime | None:
        return await db_session.scalar(
            select(ChoreOccurrence.scheduled_for).where(
                ChoreOccurrence.chore_id == chore_id,
                ChoreOccurrence.status == OccurrenceStatus.open,
            )
        )

    before = await slot_of(deleted.id)
    resp = await client.patch(
        f"/api/v1/households/{household.id}", json={"timezone": "Pacific/Niue"}
    )
    assert resp.status_code == 200

    # The live chore moved; the soft-deleted one did not.
    assert await slot_of(live.id) == datetime(2026, 8, 5, 11, 0, tzinfo=UTC)
    assert await slot_of(deleted.id) == before


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


async def test_an_offset_equivalent_rename_reports_nothing_rescheduled(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
) -> None:
    """`reanchor_open_occurrences` returns rows *moved*, not rows locked.

    Europe/Amsterdam and Europe/Paris share an offset year-round, so reinterpreting every wall
    clock lands each slot on the instant it already held: nothing is rescheduled and SQLAlchemy
    emits no UPDATE. Counting the locked rows instead would report work that did not happen, and
    `commit_household_update` gates its "a chore was completed while the timezone was changing"
    409 on exactly this number.
    """
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household, start_date=date(2026, 8, 5), repeats=RepeatPeriod.yearly
    )
    before = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    await db_session.refresh(household)

    # The zone genuinely changes, so the guards in `apply_timezone_change` do not short-circuit
    # it - the work runs and finds nothing to do.
    assert await apply_timezone_change(db_session, household, "Europe/Paris") == 0
    assert household.timezone == "Europe/Paris"

    after = await db_session.scalar(
        select(ChoreOccurrence.scheduled_for).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert after == before
    # ...and a real move does report the work, so the zero above is a measurement rather than a
    # function that always returns nothing.
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


# --- what a closure reads, and when -----------------------------------------
#
# The race these two describe needs two real transactions and so cannot be driven here (see the
# note in CLAUDE.md). What IS reachable is the half that makes the fix work: both operands are
# read *after* the row lock rather than taken from the objects the handler preloaded. Changing the
# row underneath the loaded object stands in for the concurrent transaction, and it fails on the
# old code for the same reason the real race did.


async def test_a_closure_reads_the_zone_after_the_lock_not_from_the_loaded_chore(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
) -> None:
    """`_close_occurrence` gets its `chore` from a plain select taken earlier, so reading
    `chore.household.timezone` would use whatever was true when the handler started. A zone change
    committing in between would then stamp `completed_timezone` with the old zone onto a row whose
    `scheduled_for` the re-anchor had already moved - mismatched operands for `days_late`, which is
    the one thing that column exists to prevent."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(household=household, assignees=[user])
    loaded = await _get_user_chore_or_404(db_session, user, chore.id)
    occ = await _open_occurrence(db_session, chore.id)
    assert occ is not None
    # Stands in for the concurrent PATCH. `synchronize_session=False` is what makes it a stand-in
    # at all: the default ORM-enabled UPDATE writes the new value onto the loaded object too, so
    # `chore.household.timezone` would already agree and this would pass on the old code.
    await db_session.execute(
        update(Household)
        .where(Household.id == household.id)
        .values(timezone="Pacific/Niue")
        .execution_options(synchronize_session=False)
    )
    assert loaded.household.timezone == "Europe/Amsterdam"

    await _close_occurrence(
        db_session,
        loaded,
        occ,
        closed_by_id=user.id,
        skipped=False,
        backdate=False,
        conflict_detail="conflict",
    )

    assert occ.completed_timezone == "Pacific/Niue"


async def test_a_closure_reads_the_slot_after_the_lock_not_from_the_loaded_occurrence(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
) -> None:
    """The other operand. The successor is anchored from `scheduled_for`, so a slot re-anchored in
    between would leave the chore on the old zone's grid - and permanently, since every later
    completion walks from that anchor. The `refresh(..., with_for_update=True)` is what re-reads
    it; without that this anchors from the stale value."""
    user = await make_user()
    household = await make_household(members=[user], timezone="UTC")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.daily,
        assignees=[user],
    )
    loaded = await _get_user_chore_or_404(db_session, user, chore.id)
    occ = await _open_occurrence(db_session, chore.id)
    assert occ is not None
    moved = datetime(2026, 8, 20, tzinfo=UTC)
    # `synchronize_session=False` for the same reason as the test above: without it the loaded
    # occurrence picks the new slot up by itself and the refresh proves nothing.
    await db_session.execute(
        update(ChoreOccurrence)
        .where(ChoreOccurrence.id == occ.id)
        .values(scheduled_for=moved)
        .execution_options(synchronize_session=False)
    )
    assert occ.scheduled_for != moved

    result = await _close_occurrence(
        db_session,
        loaded,
        occ,
        closed_by_id=user.id,
        skipped=False,
        backdate=False,
        conflict_detail="conflict",
    )

    # One day on from the slot as it is *now*, not from the 5 August the handler loaded.
    assert result.next_due == moved + timedelta(days=1)


# --- recording a completion on its due day ----------------------------------
#
# `backdate` dates a closure at the end of the occurrence's own local day instead of at the
# moment the button was pressed, so the chore somebody did and forgot to tick reads as on time
# and its successor advances one slot rather than jumping past everything that was missed. Which
# day that is, and when it ends, is the household's question - so every case here would answer
# differently with the zone dropped.


async def test_a_backdated_closure_lands_on_the_households_midnight_not_utcs(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user()
    household = await make_household(members=[user], timezone="Pacific/Kiritimati")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 6),
        repeats=RepeatPeriod.daily,
        assignees=[user],
    )
    # 23:00 on the 8th in Kiritimati, so the 6 August slot is two days overdue there.
    pin_clock(monkeypatch, datetime(2026, 8, 8, 9, 0, tzinfo=UTC))
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert resp.status_code == 201
    closed = await db_session.scalar(
        select(ChoreOccurrence).where(ChoreOccurrence.id == resp.json()["id"])
    )
    assert closed is not None
    # The end of 6 August in Kiritimati (+14). This is the assertion that discriminates: with
    # the zone dropped it would be 2026-08-05T23:59:59.999999Z, ten hours out and on the
    # wrong local date. The successor below is the same instant either way, since a daily
    # step is 24 hours in any zone without a transition - so it pins the derivation, not the
    # zone, and is here for that.
    assert closed.completed_at == datetime(2026, 8, 6, 9, 59, 59, 999999, tzinfo=UTC)
    assert closed.completed_at.astimezone(KIRITIMATI).date() == date(2026, 8, 6)
    upcoming = await db_session.scalar(
        select(ChoreOccurrence).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert upcoming is not None
    # 7 August local: one slot on, still overdue. Not the 9th, which is where completing
    # without the flag lands it (see test_chore_complete.py's control pair).
    assert upcoming.scheduled_for == datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    assert upcoming.scheduled_for.astimezone(KIRITIMATI).date() == date(2026, 8, 7)


async def test_a_backdated_closure_clamps_to_now_while_the_local_day_is_still_running(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-operand-crosses-midnight case, which is the only shape that catches a dropped
    zone here (see `test_days_until_due_is_the_reported_bug` for the same trap).

    Niue is -11, and the clock is set to 19:00 on 5 August there - so the slot is due *today*
    in the household while its UTC day ended six hours ago. The end of the local day is
    therefore still ahead, the clamp fires, and the closure is dated now. Read against a UTC
    day the end of the 5th is already in the past, the clamp does not fire, and the closure is
    dated seven hours before the work: a completion the household never made.

    It is also why nothing on the server re-checks overdue-ness. A caller that asks to backdate
    a chore that is not late gets `now`, which is on time anyway."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Pacific/Niue")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.daily,
        assignees=[user],
    )
    now = datetime(2026, 8, 6, 6, 0, tzinfo=UTC)
    pin_clock(monkeypatch, now)
    client = await auth_client(user)

    resp = await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    assert resp.status_code == 201
    closed = await db_session.scalar(
        select(ChoreOccurrence).where(ChoreOccurrence.id == resp.json()["id"])
    )
    assert closed is not None
    assert closed.completed_at == now
    # The UTC-dropped answer, spelled out so the assertion above cannot be read as trivial.
    assert closed.completed_at != datetime(2026, 8, 5, 23, 59, 59, 999999, tzinfo=UTC)
    upcoming = await db_session.scalar(
        select(ChoreOccurrence).where(
            ChoreOccurrence.chore_id == chore.id,
            ChoreOccurrence.status == OccurrenceStatus.open,
        )
    )
    assert upcoming is not None
    assert upcoming.scheduled_for.astimezone(NIUE).date() == date(2026, 8, 6)


async def test_a_backdated_closure_stays_on_time_after_the_household_moves(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    auth_client: AuthClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`completed_timezone` is the same zone the backdate was built from, so both operands of
    `days_late` move together and a household relocating cannot re-score a closure that was
    recorded as on time. Without the snapshot this reads 1 day late afterwards."""
    user = await make_user()
    household = await make_household(members=[user], admin=user, timezone="Pacific/Kiritimati")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 6),
        repeats=RepeatPeriod.daily,
        assignees=[user],
    )
    pin_clock(monkeypatch, datetime(2026, 8, 8, 9, 0, tzinfo=UTC))
    client = await auth_client(user)
    await client.post(f"/api/v1/chores/{chore.id}/complete", json={"backdate": True})

    entry = (await client.get("/api/v1/completions")).json()["items"][0]
    assert entry["days_late"] == 0
    assert entry["completed_timezone"] == "Pacific/Kiritimati"

    await apply_timezone_change(db_session, household, "Pacific/Niue")
    await db_session.commit()

    assert (await client.get("/api/v1/completions")).json()["items"][0]["days_late"] == 0


async def test_a_backdated_closure_reads_the_slot_after_the_lock(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The twin of `test_a_closure_reads_the_slot_after_the_lock_not_from_the_loaded_occurrence`,
    for the operand the backdate adds. The date a closure is recorded against comes from the slot
    as it is under the lock, never from the one the handler preloaded - otherwise a zone change
    committing in between dates the completion to a day the occurrence is no longer on."""
    user = await make_user()
    household = await make_household(members=[user], timezone="UTC")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.daily,
        assignees=[user],
    )
    # Pinned past the slot the update below moves it to, or the clamp fires and dates the
    # closure now - which would pass on the stale read as well and pin nothing.
    pin_clock(monkeypatch, datetime(2026, 8, 25, 9, 0, tzinfo=UTC))
    loaded = await _get_user_chore_or_404(db_session, user, chore.id)
    occ = await _open_occurrence(db_session, chore.id)
    assert occ is not None
    moved = datetime(2026, 8, 20, tzinfo=UTC)
    # `synchronize_session=False` for the same reason as its neighbours: without it the loaded
    # occurrence picks the new slot up by itself and the refresh proves nothing.
    await db_session.execute(
        update(ChoreOccurrence)
        .where(ChoreOccurrence.id == occ.id)
        .values(scheduled_for=moved)
        .execution_options(synchronize_session=False)
    )
    assert occ.scheduled_for != moved

    await _close_occurrence(
        db_session,
        loaded,
        occ,
        closed_by_id=user.id,
        skipped=False,
        backdate=True,
        conflict_detail="conflict",
    )

    # The end of 20 August, not of the 5th the handler loaded.
    assert occ.completed_at == datetime(2026, 8, 20, 23, 59, 59, 999999, tzinfo=UTC)


async def test_a_backdated_closure_reads_the_zone_after_the_lock(
    make_user: MakeUser,
    make_household: MakeHousehold,
    make_chore: MakeChore,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other operand. A day ends at a different instant in every zone, so the backdate has
    to be built from the zone read under the lock - the same one `completed_timezone` is stamped
    with, which is what keeps `days_late` reading both halves of one calendar."""
    user = await make_user()
    household = await make_household(members=[user], timezone="Europe/Amsterdam")
    chore = await make_chore(
        household=household,
        start_date=date(2026, 8, 5),
        repeats=RepeatPeriod.daily,
        assignees=[user],
    )
    # Pinned so the case does not depend on the real date sitting after 5 August 2026: before
    # it the clamp would fire and the closure would be dated now whatever zone was read.
    pin_clock(monkeypatch, datetime(2026, 8, 25, 9, 0, tzinfo=UTC))
    loaded = await _get_user_chore_or_404(db_session, user, chore.id)
    occ = await _open_occurrence(db_session, chore.id)
    assert occ is not None
    await db_session.execute(
        update(Household)
        .where(Household.id == household.id)
        .values(timezone="Pacific/Niue")
        .execution_options(synchronize_session=False)
    )
    assert loaded.household.timezone == "Europe/Amsterdam"

    await _close_occurrence(
        db_session,
        loaded,
        occ,
        closed_by_id=user.id,
        skipped=False,
        backdate=True,
        conflict_detail="conflict",
    )

    assert occ.completed_timezone == "Pacific/Niue"
    # The stored slot is 5 August in Amsterdam (22:00Z on the 4th), which in Niue is still the
    # 4th - so the day it ends is the 4th's, at 10:59:59.999999Z on the 5th. Read against the
    # stale Amsterdam zone it would be 21:59:59.999999Z on the 5th, eleven hours out and paired
    # with a `completed_timezone` saying Niue: the mismatched operands `days_late` must never see.
    assert occ.completed_at == datetime(2026, 8, 5, 10, 59, 59, 999999, tzinfo=UTC)


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
