# Timezones

Per household (`households.timezone`, IANA name in a `String(64)`, closed set enforced at
the schema layer). A household is a physical place, so the zone belongs to it, not to a
user.

## The invariant

> **`chore_occurrences.scheduled_for` is local midnight of the day the chore is due, in its
> household's zone.**

5 August in Amsterdam is `2026-08-04T22:00Z` in summer, `2026-01-04T23:00Z` in winter, and
reads back as local midnight on the 5th either way. Answered in UTC, `days_until_due` told
someone in Amsterdam at 01:30 that today's chore was due tomorrow.

## What must never be re-anchored

| Value | Why it stays put |
|---|---|
| `completed_at` | A plain instant, correct in every zone. Only the day boundary it is *read against* was ever wrong. |
| `scheduled_for` of a `manual` chore | The moment it became available, not a calendar anchor. |

The timezone migration excludes both, as does `reanchor_open_occurrences`.

This is about re-anchoring, not about the value being `clock.now()`. `completed_at` is
*chosen* at write time — now, or the end of the occurrence's local day when the caller
passes `backdate` (see [chores.md](chores.md#backdating-a-completion)). Both are honest
answers to "when was this done"; rewriting one afterwards is the lie.

`chores.start_date` stays a plain `date`: it records the day the household means to start,
and `first_occurrence` is the single place that turns it into an instant. That is why the
column, the wire type and `ChoreForm`'s Calendar needed no change. Do not "fix" it into a
timestamp.

## Arithmetic

DST correctness is free, but only on datetimes carrying a `ZoneInfo`: Python adds to an
aware datetime's wall-clock *fields* and keeps its tzinfo, so `dt + timedelta(days=1)` is
"the same local time tomorrow" and `_add_months`' `replace()` behaves the same. Every
function in `core/chores.py` converts to `tz` first; doing the arithmetic on a UTC-aware
value drifts by an hour twice a year. Where a step lands on a local time that does not
exist, `fold=0` resolves it to a real instant on the correct date.

**Never `AT TIME ZONE <column>` at runtime.** Postgres carries its own tz database, so a
name Python and Postgres do not share raises *inside the query* — a 500 from SQL rather
than a 422 from a validator. The zone maths is Python's, which is why `local_day_bounds`
exists. The timezone migration is the one exception, safe only because every row holds the
same hardcoded zone at that point.

`household_zone` falls back to UTC on an unknown name rather than raising: it runs on read
paths spanning every household a user belongs to, so raising would take out My Chores,
History and Statistics for everyone in a household holding one bad row. Unreachable through
the API, which validates against `available_timezones()` on write.

## Spanning several households

Home and Statistics have no single day window. Both call `zones_in_scope`
(`core/households.py`) and OR one `local_day_bounds` clause per distinct zone, seeded with
`false()` — the right answer for a user in no household, and it keeps the expression off
SQLAlchemy's deprecated argument-less `or_()`.

Statistics also buckets each completion by *its* household's local day and seeds its chart
axis over the union of the per-zone ranges. Two traps:

- The per-row zone comes from a **joined `Household.timezone`**, not a dict keyed off
  `zones`. The session is READ COMMITTED, so a membership changing between the two
  statements would make a subscript 500 the page.
- `axis_windows` falls back to a UTC window when the zone set is empty, because a
  helper-only caller reaches deputy nowhere and still gets a 200. Without the floor their
  chart is `[]`, which recharts renders as blank space rather than a flat line.

## Changing a household's zone

`apply_timezone_change` -> `reanchor_open_occurrences` reinterprets each open slot's
wall-clock reading in the new zone, so "due 5 August" still says 5 August. Done rows stay
put — a clean win rather than a trade, because of `completed_timezone` below.

Every candidate goes through `free_slot_from`, since the new instant can land on a slot the
chore already completed. The select takes `FOR UPDATE OF chore_occurrences` so a concurrent
`POST /complete` cannot flip a row to `done` between the read and the write.

**`commit_household_update` owns the re-anchor as well as the commit**, because that is
where a collision is raised: the re-anchor writes row by row and `free_slot_from`'s SELECT
autoflushes the previous iteration on the way past (observed as `['UPDATE', 'SELECT']`,
since `async_sessionmaker` leaves `autoflush` on). A `try` around `commit()` alone would let
`uq_occurrence_chore_scheduled` escape as a 500 while the docstring promised a 409.

`apply_timezone_change`'s two guards are about work, not correctness: re-anchoring an
unchanged zone writes nothing anyway, so they save one query per open occurrence on a plain
rename. Both the user PATCH and its admin twin call the shared helper.

### The lock is only half of it

`FOR UPDATE` delays a concurrent completion's *write*; it does nothing about the read that
completion already took. `complete` / `skip` load their chore and occurrence from plain
selects before `_close_occurrence` runs, and nothing carries a `version_id_col`, so a zone
change committing in between left the closure computed from a slot and a zone that no
longer belonged together — silently.

Measured on an Amsterdam-to-Niue move: the successor anchored 11 hours off the grid and
*stayed* there (later completions walk from that anchor), and `completed_timezone` was
stamped with the old zone onto a row the re-anchor had already moved, reporting 1 day late
where the answer is 0.

So `_close_occurrence` re-reads **both** operands after `refresh(occ, with_for_update=True)`
— the lock first, then the zone by its own select, never from `chore.household`. Whichever
transaction takes the row first, the other either re-reads what it wrote or finds the row
already `done` and skips it.

A one-row lock rather than `pg_advisory_xact_lock(household_id)`, because the row is what a
completion already contends on and a household-wide lock would serialise housemates
completing different chores. The residual: `undo_completion` reopening a row after the
re-anchor's select has run leaves that row on the old grid until the next edit re-seeds it
through `_reconcile_open_occurrence`. Narrower, and self-healing, so it is documented rather
than locked.

## `completed_timezone`

`chore_occurrences.completed_timezone` snapshots the zone a closure was judged in.
`closure_zone` (`core/occurrences.py`) is the only place its NULL fallback is written down.

Lateness is a *calendar* judgement — `completed_at`'s local date minus `scheduled_for`'s —
so read against the household's *current* zone it moved whenever the household did. A slot
at 22:00Z with a completion at 21:00Z the next day is 0 days late in Amsterdam and 1 in
`Pacific/Niue`, silently re-scoring History's badge, `punctuality` and `on_time_rate`.
Reading both operands in the snapshot makes the answer immutable, exactly as snapshotting
`title` makes history survive a rename.

- **Shifting `completed_at` is not the alternative, and reviewers keep proposing it.** It is
  the instant the work happened and is load-bearing as an absolute: stats windows filter on
  it, Home's "done today" compares it to real day bounds. Reinterpreting its wall clock
  produces a *different instant* — measured at 12 hours out for Amsterdam to Kiritimati.
- **Re-anchoring the done `scheduled_for` is not either.** It works on the first case you
  try and does not generalise: a completion at 23:30 local on its due day reads 0 days late
  in Amsterdam and 1 after the same move, re-anchored or not.
- **Only historical judgements read the snapshot**: `days_late`, the stats bucket key, and
  History's rendering of `completed_at` (on the wire as `HistoryEntryRead.completed_timezone`
  for exactly that). A row must not render its timestamp in a different zone from the one
  its lateness was computed in — a closure at 21:00Z reads "5 Jul, 23:00 / on time" in
  Amsterdam and "6 Jul, 11:00 / on time" against a 5 July due date once the household moves
  to Kiritimati. `days_since` on Unscheduled and Home's "done today" window are the other
  side of the line: anchored to *now*, so they use the current zone. Pairing a snapshot
  operand with a live one compares two calendars.
- **NULL** means "not judged yet" (every open row) or "closed before the column existed",
  where the fallback is the household's current zone — the old behaviour, and all the
  backfill can honestly reconstruct.

The timezone migration re-anchors done rows too (no `status` filter), which is right there
and wrong at runtime: one statement applying a uniform downward shift to rows all at
midnight UTC cannot collide, while row-by-row ORM writes shifting *forward* can put one row
onto a slot the next has not vacated.

## Frontend

Household timestamps render in the household's zone, via the optional `timeZone` argument on
the three formatters in `lib/format.ts` and `lib/chores.ts`. It is carried on
`ChoreHouseholdRead`, embedded in five payloads, so one field reaches Home, Unscheduled,
History, the chore reads and the filter options. Without it a slot stored at 22:00Z prints
"4 Aug" beside a server-computed "Due today" meaning the 5th.

Account and admin surfaces (a user's `created_at`, an invitation's expiry) keep the
viewer's zone: those belong to no household.

## Migrations

`chore_occurrences.updated_at` has its own revision (`c8d5e21a473f`), deliberately not
bundled with the timezone work even though `d7a3f81c62b4` already rewrites that table: an
operator rolling the timezone feature back should not have to drop an unrelated column.

Added nullable, backfilled from `created_at`, then set NOT NULL with a `now()` default —
three statements rather than one `ADD COLUMN ... NOT NULL DEFAULT now()`, because `now()` is
volatile and forfeits Postgres's metadata-only fast path, making the one-liner two full
table rewrites instead of one.

## Testing

`tests/test_timezones.py`. Two conventions worth copying: extreme zones
(`Pacific/Kiritimati` +14, `Pacific/Niue` -11) over plausible ones, since they straddle UTC
and fail loudly if a zone is dropped; and every household fixture defaulting to
`timezone="UTC"`, which keeps several hundred pre-timezone due assertions elsewhere meaning
what they used to.

Two traps, both instances of the
[satisfy-every-other-clause rule](../../guidelines.md#satisfy-every-other-clause):

- **The obvious regression test pins nothing.** "At 01:30 in Amsterdam the chore reads as
  due today" passes even with the comparison reverted to UTC: the slot sits at 22:00Z and
  the clock at 23:30Z, so both shift by the same two hours. A zone only changes the answer
  where exactly *one* operand crosses midnight — 23:00 local is such a moment, and
  `test_home_uses_the_household_day_late_in_the_evening` is the test that actually fails.
- **`end - start` on two aware datetimes sharing a tzinfo ignores the zone** and subtracts
  wall-clock fields, so "this DST day is 25 hours long" is a constant 24 unless both sides
  are `.astimezone(UTC)`'d first.

`chore_occurrences.updated_at` cannot be observed moving under the fixtures: both defaults
are SQL `now()`, i.e. `transaction_timestamp()`, frozen for the whole savepoint-wrapped
test. The suite pins the column's configuration; the elapsed behaviour is a by-hand check
(complete a chore on the dev stack, compare the two columns).

**The zone-change / completion race is by-hand only.** The savepoint fixtures give each test
one connection, so two concurrent transactions never exist. Drive it with a throwaway script
that builds its own household, chore and open occurrence, then `asyncio.gather`s two
`async_session_factory()` sessions: one calling `apply_timezone_change` and sleeping before
it commits, the other calling `_close_occurrence` partway through that sleep. Assert
`completed_timezone` matches the household's zone and the successor sits on local midnight.
Run it against the reverted code first — it must fail — and clean up after itself.

What *is* reachable is the half that makes the fix work: both operands read after the lock
rather than from the preloaded objects. `update(...)` with
`execution_options(synchronize_session=False)` stands in for the concurrent transaction, and
that option is load-bearing — the default ORM-enabled UPDATE writes the new value onto the
loaded object too, so the test would pass on the old code. Both tests assert the object is
still stale before closing, for that reason.
