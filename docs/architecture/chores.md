# Chores, occurrences and assignment

## The two core modules

**`core/occurrences.py` is the DB-touching layer over `core/chores.py`, which stays pure.**
The latter knows where the recurrence grid falls; the former knows which slots a chore has
actually used (`free_slot_from`, `initial_slot`, `rule_for`, `zone_for`,
`reanchor_open_occurrences`).

It exists as its own module rather than as private helpers in the chores router because two
routers need it — the chores one and the household one, which re-anchors slots on a timezone
change — and `api/v1/chores.py` already imports from `api/v1/households.py`, so the reverse
would be an import cycle.

The pure helpers take `now` as a parameter and need no clock seam; the endpoints call
`clock.now()`.

## Who is on the hook now

`chore_occurrences.assignee_id` on the single open occurrence, **not** a column on the
chore. The pool is `chore_assignees`; the rotation order is computed, never stored
(`app/core/assignment.py`).

Every live chore has exactly one open occurrence whatever its period, so
`current_assignee: null` means unassigned/shared and never "nothing left to do".

The API honours an explicit `current_assignee_id` for **every** strategy, not just `manual`
(`_reconcile_open_occurrence`, deliberately ungated). The picker in `ChoreForm` therefore
shows for `manual` always, and for the auto strategies only where the page passes
`allowAssigneeOverride` (edit does, create does not, so a random chore's first assignee stays
random) — and in both cases only with a non-empty pool.

The load-bearing part is that `current_assignee_id` stays derived against the live pool: that
is what lets the payload gate more loosely than the render (on the strategy, not also on the
pool) and still never submit a stale or hidden value, since an empty pool forces `null`
either way. For the auto strategies an override lasts until the next turn boundary, because
completing re-derives through `_successor_assignee` (or, for calendar turns, any closure over
the boundary re-derives through `_calendar_turn_assignee`, skips included) — which is what the
`currentAssigneeTurnHint` copy promises the user, so keep them in step.

### `least_done` reads a tie as a handover

The one rule in this module that is not obvious from the name. `next_assignee` takes the
minimum, then drops whoever is on the hook from the tied set: two people level means the
chore moves across, never another turn for whoever sorts earlier.

It used to be a plain `min` over the alphabetically ordered pool, which re-picked whoever
sorted first, so a chore that was already theirs stayed theirs — reported as "1 and 1, and it
stayed put" (#58).

**Only a tie, though.** Somebody genuinely behind keeps the chore while they catch up, so
this is deliberately NOT `random`'s blanket exclusion of `current`; make it one and
`least_done` becomes `alphabetical` with extra steps.

A test for it has to put the person on the hook **first** alphabetically, or it passes either
way — which is why the bug survived two tie tests that both happened to tie on the second
name.

### The exclusion anchors on the assignee, not the completer

`occ.assignee_id`, NOT whoever was credited with the completion. Somebody other than the
person on the hook completing a chore is an everyday event: `complete_chore` defaults the
credit to the *caller*, any member may complete any chore, and `Home.tsx`'s `requestCredit`
skips the credit dialog entirely when the caller is one of the chore's assignees — **any** of
them, rather than the one who is up.

But that alone never reaches the tie rule. **With the default `turn_length` of 1 and two
assignees the two anchors cannot disagree**: the chore sits with whoever is behind, so a
completion by anyone else only pushes that person further ahead, leaving the one behind
strictly least and holding it — no tie forms. A tie needs the person who is up to do it
themselves, and then both anchors name them. Taking turns, a manual override, or a third
assignee is what makes them different people at a tie.

Where they do differ, **the turn is the unit to reason in** — the product call, raised and
settled with the reporter. With `turn_length` 2, Anna holds the turn and Bob does one of the
two, so the turn that just ended was *Anna's* and the next belongs to somebody else, whoever
happened to do the work inside it. Three mechanical reasons agree:

1. The ask was to force the *assignment* to move.
2. `alphabetical` steps from `current` and `random` excludes it, so any other anchor makes
   `least_done` the one strategy whose rotation reads a different column.
3. `complete_chore` lets any caller credit *themselves* whether or not they are in the pool,
   so excluding the completer would silently do nothing for a non-assignee.

`_completion_tally` keys on `completed_by_user_id`, so it carries the completer's work either
way — only who is up next is at stake.

### Five consequences

**`initial_assignee` takes the tally too, and breaks its ties by name alone**, there being no
current assignee for a repeat to be a repeat *of*. It is the fallback wherever there is
nobody to hand over from, and it is reached two ways:

- **`_strategy_pick` (`api/v1/chores.py`) is the funnel for every handler-side derivation**:
  `create_chore`, both branches of `_reconcile_open_occurrence`, and the stale-assignee case
  of both `_retained_assignee` and `_successor_assignee`. Keep it that way — a handler calling
  `initial_assignee` directly ranks alphabetically on a chore with history, which is what all
  of these did before and what quietly undid the strategy.
- **Inside `next_assignee` itself** (`assignment.py`, the "current is not in the pool"
  branch), which is not routed through `_strategy_pick` and cannot be, being pure. It hands
  its own `counts` down, and that argument is load-bearing the same way: drop it and an
  unassigned `least_done` chore degrades to alphabetical at every turn boundary. Pinned by
  `test_next_least_done_fallback_still_ranks_on_the_counts`.

`create_chore` and a revive with no closure behind it genuinely have nothing to tally, and
are funnelled anyway rather than special-cased: the query returns `{}` and the answer is the
alphabetical one either way, so the alternative is an unwritten "this chore cannot have
history yet" invariant carried by a comment. The gate inside `_strategy_pick` (`least_done`,
pool of two or more) is about *cost* rather than the answer — nothing else reads `counts`, and
`initial_assignee` returns before consulting them for a smaller pool. `counts` is therefore
optional, and omitting it is *identical* to the old alphabetical arm (every key reads 0, so
`min` returns the first), which is what lets `db/seed.py` and the `make_chore` fixture keep
calling it untallied.

**One tally read serves the turn and the ranking** (`_completion_tally`): the total decides
whether `should_reassign` fires, the per-member split feeds `least_done`, and they come off
one GROUP BY rather than a COUNT plus a GROUP BY over identical rows.

**The total is not `sum(counts.values())`** and must not be "tidied" into it:
`completed_by_user_id` is `ON DELETE SET NULL`, so a hard-deleted user leaves done rows
crediting nobody, which spent a turn but can be credited to no one. Deriving the total from
the split would shorten every turn sitting behind such a row.
`test_complete_counts_a_closure_crediting_nobody_towards_the_turn` catches it.

**The post-completion snapshot requirement survives, but its reason changed.** A stale tally
no longer means "never rotates"; it leaves the finisher a completion short, so a real tie
reads as a strict minimum and they hold one extra turn. `_close_occurrence` flushes before
`_successor_assignee`, which is what makes it honest.

**A stale assignee is re-derived on every way out of a closure; an unassigned row survives a
skip always, and a completion up to the next turn boundary.** Those are different states and
the code has to keep asking which it holds: NULL means the chore was handed back to the
household deliberately, while a row naming somebody the pool no longer holds is a gap.

Only the two mid-turn paths make the distinction — `_retained_assignee` and
`_successor_assignee`'s `not should_reassign` branch — each testing
`current_assignee_id is not None` alongside the missing pool member. At a turn boundary there
is no distinction to make: `next_assignee` re-derives *both*, because `_in_pool` is
`user is not None and any(...)` and so answers False for a NULL assignee and a departed one
alike. That is why a clear dies on the boundary rather than lasting forever, which is the
documented promise.

Completing used to answer NULL for the stale case mid-turn, so one state re-derived on a skip
and silently unassigned on a completion. Both clauses of the new guard are pinned separately —
deleting only the `current_assignee_id is not None` half left the whole suite green until
`test_complete_mid_turn_leaves_a_deliberately_cleared_chore_unassigned` existed.

**`_retained_assignee`'s stale-assignee fallback is reachable, and only through undo.** An
edit cannot leave somebody it just dropped from the pool on an open row —
`_reconcile_open_occurrence` is exactly what moves them off — but `undo_completion` reopens a
*done* row with the assignee it closed on, and done rows are never reconciled. So: complete,
drop that person in an edit, undo, skip. Pinned by
`test_skipping_after_an_undo_resurrects_a_departed_assignee_uses_the_tally`.

### Clearing is its own field

**`clear_current_assignee` cannot be folded into `current_assignee_id: null`.** Null already
means "no explicit choice", and `_reconcile_open_occurrence` then *keeps* an assignee who is
still in the pool — which is load-bearing, because `ChoreForm` submits null routinely whenever
the picker is hidden (empty pool, or an auto strategy on create). If null cleared the
assignee, editing a random chore's title would silently unassign it. "Nobody" and "no opinion"
are two different messages.

The clear branch must come **first and stop there** in that function: falling through to the
recompute `elif` would immediately re-derive somebody from the strategy and undo it.

In the form the choice is a `UNASSIGNED` sentinel option rather than `value=""`, which Radix
reserves for "nothing selected" and would render as the placeholder.

### Calendar turns ("Skips use up the turn")

`chores.turns_follow_calendar`. By default a turn is `turn_length` **completions**
(`should_reassign` over `_completion_tally`) and a skip never spends one. That is what stops a
skip pushing work onto a housemate, but it also means "Naomi has it this week" drifts
mid-week as soon as a day is skipped. With the flag on, a turn is `turn_length` **grid slots
counted from `start_date`** instead: `slot_index` places the closed slot and its successor, and
`crosses_turn` hands over when they fall in different turns. A daily chore with a 7-slot turn
that starts on a Monday therefore changes hands every Monday, however the week went.

What to keep straight:

- **The phase comes from `start_date`, not from the occurrence chain.** This is the one place
  that reasons on a lattice from the start date (see `core/chores.py`'s module docstring for
  why everything else does not). Once the chore has completions, editing the start date
  re-phases the turns without moving the open slot, which is how an existing chore is put onto
  Mondays. (With none, the edit re-seeds the open slot from the new date as usual.) `slot_index` floors, so
  an open slot left off that lattice by a re-phasing edit still gets an answer.
- **Monthly and yearly count calendar months, not days.** The chain's day of the month drifts
  (Jan 31 -> Feb 28 -> Mar 28), so a day-exact lattice has no closed form, while every step
  is exactly `interval` months. Counting months keeps `slot_index` constant-time, which
  matters because it runs twice on every closure with a caller-chosen start date.
- **Swallowed slots count.** A late completion jumps past the missed slots and leaves no rows
  for them, which is why this counts on the calendar rather than counting done and skipped
  rows. For the same reason the boundary test compares turn numbers, never `next % length`: a
  jump rarely lands *on* the boundary slot.
- **Several turns at once still hand over once** (the product call): the next person, not
  whoever's turn it would be by now.
- **A skip over the boundary hands over**, unlike `_retained_assignee`. Inside a turn both
  paths hold through `_held_assignee`, the same helper the completion-counted turn uses, so a
  cleared row stays cleared and a stale one is re-derived exactly as it is there.
- **`least_done` still ranks on work done.** Only the *timing* of a turn moves to the
  calendar; the tally passed to `next_assignee` still excludes skips.
- **The schema forces it off** where it means nothing (turn length 1, unscheduled, the
  `manual` strategy), and the form defaults it **on** for a new chore but keeps the stored
  value on edit. The UI label is "Skips use up the turn", explained behind an `InfoHint` icon.
  It used to read "Ignore skipped", which said the opposite of what the option does.

## Skipping several occurrences

`SkipChoreRequest.count`, and `due_count` on every Home row. A chore ignored for a week has
eight occurrences due (the open one, the missed ones, today's), and the skip dialog asks
whether to skip one of them, all of them, or a custom number up to that many. It asks only
when more than one is due; otherwise it is the plain confirm it always was.

What to keep straight:

- **One skipped row per slot.** Skipping three leaves three history rows, so "most skipped"
  and punctuality count what was really missed. This includes "all": a skip used to swallow
  the whole backlog into a single row, and now writes one per due slot.
- **`count: null` (or no body) means every due slot**, so a client that sends nothing lands
  where a skip always landed. `due_slots` runs the same loop as `advance_anchor` and stops
  at the same place, which is what makes that true by construction rather than by test.
  **The dialog never sends null once a number is on screen**, "all" included: the count the
  user saw is the only guard against a stale page. Sent as null, a dialog opened before a
  housemate completed the chore would skip tomorrow's slot with a 201; sent as the number, it
  gets the 400 instead. Only the plain one-or-none confirm sends no body.
- **The cap is the due count**, a 400 above it, because how many are due depends on the chore
  rather than on the request. A chore with nothing due still accepts a single skip: that is
  the endpoint's documented latitude, and the count is what may not reach into the future.
  Both are resolved after the row lock, from the slot it re-read, and before anything is
  written.
- **The assignee is decided once**, from the first slot to the successor. A completion-counted
  turn never moves on a skip however many slots it spans, and a calendar turn hands over at
  most once (the same call as "several turns at once still hand over once" above). So the
  extra rows all carry the assignee the chore was closed with, and the closure never loops
  over `_calendar_turn_assignee`. Walking a backlog with backdated completions differs here,
  by design: those are separate requests, one closure each.
- **Extra rows are inserted in slot order**, so `undo_completion`'s `max(id)` reopens the
  latest of them and an undo walks back one slot at a time.
- **A slot the chore already has a done row for is passed over**, for the reason
  `free_slot_from` exists: an open slot re-seeded into the past can sit behind history, and
  inserting it again would be a 409 no retry clears.
- **The dialog's unit follows the period only when it can.** "3 days" is true for a plain
  daily chore; every 2 days or a week pinned to Tue and Fri say "3 occurrences" instead.

## Who a skip is recorded against ("Skip as …")

`SkipChoreRequest.completed_by_user_id`. A skip used to be recorded against whoever pressed
the button, full stop. Now Home asks, exactly when Done asks "who gets the credit?": skipping
a chore assigned only to other people opens `CreditDialog` in `action="skip"` mode ("Skip as
{name}" / "Skip as me"), after the count dialog. An unassigned chore, or one you are already
an assignee of, is recorded against you without asking. Both paths share `creditsMe` on the
frontend and `_credited_user_id` on the backend, so the two dialogs open in the same cases
and accept the same people: yourself always, otherwise only a current assignee (400).

What to keep straight:

- **It changes who the row names, nothing else.** The turn rules read the assignee and the
  done tally, never `completed_by_user_id` on a skipped row, so crediting a skip moves no turn.
- **The row then belongs to that person, undo included.** `undo_completion` allows the person
  the row names or an organiser, so whoever pressed "Skip as Ben" cannot undo it themselves
  (and a helper no longer sees it on History). The same trade-off "Done as" already makes,
  accepted rather than adding a "submitted by" column.
- **Every row of a multi-slot skip names the same person**: `_record_extra_skips` copies it
  from the first row.
- **Only Home passes `skip`.** Unscheduled chores are never skipped, so their page never needs
  the skip copy, which is why the keys live under `home.creditSkip` alone.
- **What reads it:** the per-chore Statistics charts below, History, and the `user_id` filter
  on `GET /stats` (which already filtered skips by `completed_by_user_id`).

## Per-chore statistics

`GET /stats/chores` (the picker) and `GET /stats/chores/{id}` (one chore's figures), shown by
`components/stats/ChoreStatsSection.tsx` under the page-wide cards. Same deputy scope, range
window and day/week bucketing as `GET /stats` (`_range_window`, `_bucket_keys` are shared), so
the numbers add up with the rest of the page. Differences worth knowing:

- **One chore is a target, not a filter**, so a chore out of scope or soft-deleted is a 404,
  not an empty answer.
- **`people` always includes the current assignees**, at zero if need be, so "never does it"
  is visible, plus anyone else with a closure in the range. Unscheduled chores are mostly
  unassigned, so theirs lists activity only.
- **A closure with no completer** (a hard-deleted user) is in nobody's row; its skip still
  counts in the bucket's `skipped`, which is why the frontend's empty state sums skips from the
  buckets rather than from the people. Its *completion* shows nowhere, a known gap that unlike
  `GET /stats` the per-chore figures do not total.
- **Timeline colours follow the user id**, not the rank, using the reserved `--chart-1..10`
  ramp; the eleventh person onwards folds into one "Others" series (`lib/choreStats.ts`).

## Backdating a completion

`CompleteChoreRequest.backdate` — the chore somebody did and forgot to tick.

Without it, completing an overdue chore silently swallows every occurrence that was missed:
`advance_anchor` rolls the grid past every slot on or before the completion date, so a daily
chore due the 6th and ticked on the 8th gets a successor of the 9th and the 7th and 8th never
existed.

With it, `completed_at` is `min(end_of_local_day(scheduled_for, tz), now)` instead of
`clock.now()`, and both wanted behaviours fall out of the existing recurrence code:
`days_late` is 0, and `advance_anchor` cannot roll, so the successor is exactly one interval
on. A backlog is then walked one completion at a time, each offering the next missed day.
Home asks through `BackdateDialog` (overdue rows only), which chains into the unchanged
`CreditDialog`.

Seven things to keep straight:

- **A flag, never a client-supplied datetime.** The server derives the instant, so there is
  no clock skew, no timestamp in the future and no dating a completion to an arbitrary day.
- **The clamp is what removes the overdue check**, rather than being defensive tidying. For a
  chore due today or completed early the end of its due day is still ahead, so the answer is
  `now` — which is on time anyway. A client that mis-decides is therefore harmless, and no
  validator has to re-derive "is this late" server-side.
- **`end_of_local_day` is derived from `local_day_bounds` and must not be hand-written.** That
  bound is *exclusive* — next local midnight, a different local date — so returning it reads
  as a day late and lets `advance_anchor` roll a slot, reintroducing the exact bug.
  Hand-building `23:59:59.999999` is wrong differently: it is ambiguous in a zone that falls
  back at midnight, where `fold=0` picks the earlier occurrence, an hour before the day ends.
- **One `now` became two, and they are not interchangeable.** The stamped column, the
  successor derivation and the echoed `created_at` take the chosen instant; `days_until_due`
  on the way out keeps the real `now`, because `GET /home` computes the same number from
  `clock.now()` and a backdated one would have the 201 call a successor "due in a day" that
  the next page load calls overdue, in the same second.
- **Refused with a 400 for `manual`.** `next_occurrence_after` returns `completed_at` verbatim
  for an unscheduled chore, so a backdated one would reopen at a day's end and collide with
  itself on `uq_occurrence_chore_scheduled` the second time it was done that day — a 409 no
  retry clears. Placed before the occurrence lookup and before the credit check, like
  `skip_chore`'s twin: it is a property of the target, so every caller gets the same answer.
- **The successor goes through `free_slot_from` on every scheduled completion**, not only
  backdated ones. Backdating lets the successor land on or before today, so a chore whose open
  slot was re-seeded into the past (the unscheduled -> scheduled round trip) can walk onto its
  own done row. Deliberately not gated on the flag: gating it would leave the same latent bug
  on the just-now path, and it is the identity whenever nothing collides. (`manual` is
  skipped, for want of a grid to walk.) What that leaves in the `IntegrityError` catch is the
  genuine concurrent race alone.
- **Three consequences that look like bugs and are not**, each pinned by a test so nobody
  "fixes" them: Home's progress bar does not count a backdated completion (it answers "how
  much of today's list did you get through", and that work was not today's); Statistics
  buckets it on the day it was due, so clearing a 40-day backlog moves nothing on a 7-day
  window; and a rotating chore advances **once per completion**, so walking three missed days
  passes three turns. (Calendar turns differ here: walking the backlog hands over at every
  boundary it crosses, where one late completion over the same span hands over once.) History
  also sorts it into the past rather than to the top, since the default sort is
  `completed_at` desc.

## Unscheduled chores

`repeats: 'manual'` — a *different* field from the `manual` assignment strategy. These are the
chores you do ad hoc: **never due, never overdue, repeatable on demand.**

Completing one flips its occurrence to `done` and opens a fresh one anchored at **the
completion timestamp** (`next_occurrence_after`), so it stays available forever. That
timestamp, not its midnight, because `uq_occurrence_chore_scheduled` is per (chore,
`scheduled_for`) and a date would collide the second time a chore was done in one day.

They used to be one-offs that terminated on completion; do NOT reintroduce that. The
migration (`3c1f04a7e9d2`) reopens the ones it left dead.

**`chores.start_date` is nullable and NULL for every one of them.** It only ever seeded the
first slot, which for an unscheduled chore means nothing, so their first occurrence opens at
creation time instead (`initial_slot`). The schema layer keeps this true from both directions
(`_normalised_schedule`): the date is silently dropped for `manual` and **required** for every
other period — the one part of the schedule rejected rather than normalised. So a NULL
`start_date` and `repeats == manual` are the same fact, and `ChoreForm` hides the field and
submits `null`.

It does not *refill* the date when the period stops being unscheduled: `startDate` is derived
(`values.start_date || todayISO(timezone)`), so an empty value resolves to today in the
**household's** zone on its own — which is also what makes it follow a household switch on the
create page. A date the form was handed, by cloning a scheduled chore, is kept instead.

**Their `scheduled_for` records availability, not a deadline.** Nothing may read it as one:
`days_late` comes back `null` from History, and both `home.py` and `stats.py` exclude
`repeats == manual` outright. In stats that means counted in `completed_in_range` /
`completions_over_time` / `per_person` (work done is work done) and excluded from
`currently_overdue` / `status_breakdown` / `active_chores` / `punctuality` / `on_time_rate`.
The live snapshot needs only ONE predicate for the first three (same query), which also
preserves "the three buckets sum to `active_chores`"; `punctuality` deliberately no longer
sums to `completed_in_range`, and `on_time_rate`'s denominator is the scheduled completions
alone.

**`most_skipped` is the one entry on that list needing neither treatment**, and the reason is
worth reading before you "fix" it. A skip can only be *recorded* against a scheduled chore,
since `skip_chore` refuses an unscheduled one, so it needs no `repeats != manual` predicate
the way `punctuality` does. But `update_chore` can switch a chore to `manual` afterwards and
its existing skipped rows survive that, so a row in the ranking CAN belong to a chore that is
unscheduled *today*. Those are kept on purpose (the skips happened, and the chore is still
there to be fixed), which makes this the one place a skip figure and `punctuality.skipped` can
legitimately disagree: the latter reads `repeats` live and drops them. Do not add a predicate
to make the two agree — it would hide chores from the list exactly when somebody has just
reacted to being nagged about one by parking it as unscheduled.

The view is `GET /api/v1/unscheduled` + `pages/Unscheduled.tsx`, ordered **alphabetically**
(sorting by slot would be a deadline in disguise) and reporting `days_since_last_completion`
instead of any due field. Its dot uses the `--done-recent/week/stale` tokens, NOT `--due-*`:
the scales cross over, since done today is green while due today is yellow.

### Three grid assumptions they break

Every one bit once already. The root cause each time: an unscheduled chore anchors its
successors at completion timestamps, so its done rows sit on **both sides** of its open one,
and "the open slot is later than every done slot" is no longer true.

1. **`undo_completion` finds the latest closure by `max(id)`** — insertion order — and NOT by
   `max(scheduled_for)`. Slots only run in completion order while they come off a grid; switch
   a not-yet-due chore to unscheduled and its next done row is dated *earlier* than the one
   before it, so ordering by slot reopens the wrong occurrence (resurrecting a future slot with
   a stale assignee while deleting the live open row). It used to order by `max(completed_at)`,
   which backdating broke.
2. **`_reconcile_open_occurrence` takes a `was_unscheduled` flag**, read in `update_chore`
   *before* the payload overwrites `chore.repeats`. Unscheduled -> recurring must re-seed the
   slot from the new `start_date` rather than `snap_to_slot` it: snapping is the identity for
   every unpinned rule, so the chore would keep its last-completion moment and read as overdue
   by however long ago that was, while the form said "start today".
3. **Every re-dated slot goes through `free_slot_from`** (`core/occurrences.py`), which walks
   it past any slot the chore has **already completed**. `first_occurrence` and every grid slot
   are both local midnight in the household's zone, so re-dating onto a grid the chore has
   history on can land exactly on a done row; `uq_occurrence_chore_scheduled` then fails the
   commit and `update_chore` returns a 409 that retrying can never clear, since the same edit
   recomputes the same occupied slot. "Did it today, parked it as unscheduled, later put it
   back on a schedule" is enough to hit it, because the form pre-fills today's date.

## Rich text descriptions

`chores.description` is sanitised HTML in a `Text` column, authored in Tiptap v3.
`backend/app/core/richtext.py` is the **single definition of the format** and the security
boundary; the editor's `extensions.ts` and `index.css`'s `.rich-text` are downstream of it.

**Sanitising happens on write, server-side, and that is not negotiable.** `/api/v1` is a JSON
API with future non-browser clients, so a browser-side allowlist proves nothing: `curl` skips
it. `SanitisedHtml` in `schemas/chore.py` puts `max_length` *inside* the `Annotated` so the cap
runs on raw markup **before** the `AfterValidator` — that ordering is what stops a mostly-junk
payload buying its way under the limit by being stripped. `target="_blank"` and
`rel="noopener noreferrer"` are **forced** onto every link (nh3's `set_tag_attribute_values`),
not merely allowed, so a payload posted with `target="_self"` is overridden rather than obeyed.
Tightening the allowlist later does NOT clean old rows; that needs its own data migration.

**Links: the editor's rule is `isAllowedUri`, never Tiptap's `protocols` option.** `protocols`
only *appends* to a hardcoded ten schemes (http, https, ftp, ftps, mailto, tel, callto, sms,
cid, xmpp), so passing our three — all already in that list — narrows nothing. Left that way
the editor accepts a `tel:` or `ftp:` link, renders it, and the server drops the href on save
with nothing shown to the user: the exact silent formatting loss this design exists to
prevent. `isAllowedRichTextUri` in `rich-text/format.ts` derives the rule from
`RICH_TEXT_LINK_PROTOCOLS`, and `sanitise_html` passes `url_relative="deny"` because
`ALLOWED_SCHEMES` bounds absolute URLs only — nh3 otherwise passes `//evil.example/x` straight
through. Whatever the server strips, the editor has to refuse, or the loss is silent again.

**"Empty" is not one value in HTML.** Every WYSIWYG emits `<p></p>`, `<p><br></p>` or
`<p>&nbsp;</p>` for an untouched editor and all three are truthy, which is what makes a bare
`if description:` wrong. `sanitise_description` collapses them to `NULL`, and `RichTextEditor`
emits `''` rather than `<p></p>`, so `ChoreForm`'s `|| null` stays correct. Two gotchas inside
`is_blank`: nh3 re-escapes on the way out, so stripping tags off `<p>&nbsp;</p>` yields the
literal `&nbsp;` and needs `html.unescape` before `.strip()`; and the unescaped form must never
be what gets stored.

**StarterKit is configured by subtraction, and that list is load-bearing.** `heading`,
`codeBlock`, `horizontalRule` and `trailingNode` are all off. The first three sit outside
`ALLOWED_TAGS`, so leaving one on means a user formats a heading, sees it look right, saves,
and gets a plain paragraph back with no error; `trailingNode` keeps a *real* trailing paragraph
that serialises, so it would make every document look non-empty. `Placeholder` (from
`@tiptap/extensions`) is the exception that IS safe to add: it is a decoration, not a node, so
it cannot touch `getHTML()` or `isEmpty`. Being CSS it is also invisible to assistive tech,
hence the `aria-placeholder` beside it.

### Read surfaces

The editor itself, and `DescriptionDialog` opened from the marker icon on `ChoreRow` (Home and
Unscheduled).

**No list sends the HTML.** Home, Unscheduled and the chores management list all carry
`has_description: bool` instead, and whoever wants the markup fetches `GET /chores/{id}`. Only
the first two *render* a marker from it; on the management list the flag is carried for shape
parity, so adding one there later needs no API change. So a household's instructions never ride
along on the landing page, and the worst-case payload of the 100-row management list is not
100 x `MAX_RICH_TEXT_LENGTH`.

That list goes further and never *reads* the column either: `list_chores` selects a labelled
`description IS NOT NULL` and applies `defer(Chore.description, raiseload=True)`, so the HTML
does not leave Postgres. The suite cannot prove that part — the fixtures share one session, so
an already-loaded chore keeps its description whatever the option says; check the compiled SQL
if you touch it.

One consequence: `Chores.tsx`'s clone action fetches the source chore before navigating,
because a clone built from the row would silently lose the description.

`RichText` is the only `dangerouslySetInnerHTML` outside `ui/chart.tsx`, and it is NOT a
sanitiser: only ever pass it something the server has already cleaned.

The management list has its own schema, `ChoreListRead` — a sibling of `ChoreRead` under
`ChoreReadBase`, carrying `has_description: bool` where the detail read carries the HTML.

`ChoreCreate` and `ChoreEdit` are `lazy()` in `App.tsx` for the same reason Statistics is: they
are the only routes reaching `ChoreForm`, and that chunk is ~146 kB gzipped. A third page
rendering `ChoreForm` needs splitting too, or the editor lands back in the main chunk.
