"""Pure, DB-free assignment logic: pick who is on the hook for a chore occurrence.

Mirrors app/core/chores.py - no database access. Callers resolve the assignee pool
(a list of User) and pass it in, along with the current assignee and, for
`least_done`, a per-user completion-count map. The chore's `assignment_type` decides
who comes next:

- manual:       never auto-rotates; the caller sets the assignee by hand.
- alphabetical: the pool ordered by (first_name, last_name, id); the next one, wrapping.
- least_done:   the pool member with the fewest completions of this chore. Ties break by
                name, except that `next_assignee` drops the person on the hook first: two
                people level is a handover, not another turn for whoever sorts earlier.
- random:       a random pool member, avoiding an immediate repeat when possible.

`random` takes an injectable `rng` (a random.Random) so tests are deterministic.
"""

import random
from collections.abc import Mapping

from app.models import AssignmentType, User


def _ordered(pool: list[User]) -> list[User]:
    """The pool in canonical alphabetical order: the same (first_name, last_name, id)
    column tuple the History filter sorts by, giving a stable rotation order and
    tiebreak. This is a Python code-point sort, so it can diverge from the SQL
    collation for mixed-case / accented names (fine for the common ASCII case)."""
    return sorted(pool, key=lambda u: (u.first_name, u.last_name, u.id))


def _in_pool(user: User | None, pool: list[User]) -> bool:
    # Compare by id: ORM identities differ across sessions and unpersisted rows.
    return user is not None and any(u.id == user.id for u in pool)


def initial_assignee(
    strategy: AssignmentType,
    pool: list[User],
    *,
    counts: Mapping[int, int] | None = None,
    rng: random.Random | None = None,
) -> User | None:
    """Who is on the hook for a chore's first occurrence, and the fallback whenever there is
    no current assignee to hand over from. A single-member pool is always that member; an
    empty pool is unassigned (shared). `manual` with more than one member returns None so the
    caller can set the current assignee by hand.

    `counts` (user id -> completions of this chore) is used by `least_done` alone, and is
    optional because three of its callers have nothing to tally: `create_chore` and the
    `make_chore` fixture both run before the chore's first occurrence exists, and `db/seed.py`
    calls this before writing any. Omitting it is behaviour-identical to the alphabetical
    answer this arm used to give unconditionally - every key reads 0, so `min` returns the
    first of `_ordered` - which is what lets those three keep calling it untallied."""
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    match strategy:
        case AssignmentType.manual:
            return None
        case AssignmentType.random:
            # Draw from the ordered pool so a seeded pick is independent of the
            # arbitrary DB row order (the assignees relationship has no order_by).
            return (rng or random).choice(_ordered(pool))
        case AssignmentType.least_done:
            # No current assignee to hand over from, so unlike `next_assignee` below a tie
            # here is broken by name alone: there is nobody it would be a repeat for.
            tally = counts or {}
            return min(_ordered(pool), key=lambda u: tally.get(u.id, 0))
        case _:  # alphabetical: first alphabetically
            return _ordered(pool)[0]


def next_assignee(
    strategy: AssignmentType,
    pool: list[User],
    current: User | None,
    counts: Mapping[int, int],
    *,
    rng: random.Random | None = None,
) -> User | None:
    """Who is on the hook for the next occurrence after `current` just completed one.
    `counts` maps user id -> completions of this chore (only used by `least_done`).

    `counts` MUST already include the completion that triggered this handoff
    (post-completion snapshot). A stale tally leaves the person who just finished a
    completion short, so what is really a tie reads as a strict minimum below and they keep
    the chore for another turn instead of handing it on."""
    if strategy == AssignmentType.manual:
        return current  # never auto-rotates; update_chore keeps it valid
    if not pool:
        return None
    if not _in_pool(current, pool):
        # No current yet, or the pool was edited to drop them: start fresh. `counts` rides
        # along so `least_done` still ranks on work done here - an unassigned chore ("nobody
        # in particular") reaches this on every turn boundary, so without it the strategy
        # would quietly degrade to alphabetical for as long as nobody is on the hook.
        return initial_assignee(strategy, pool, counts=counts, rng=rng)
    if len(pool) == 1:
        return pool[0]
    match strategy:
        case AssignmentType.alphabetical:
            ordered = _ordered(pool)
            i = next(n for n, u in enumerate(ordered) if u.id == current.id)
            return ordered[(i + 1) % len(ordered)]
        case AssignmentType.random:
            # Ordered so a seeded draw is independent of arbitrary DB row order.
            others = [u for u in _ordered(pool) if u.id != current.id]
            return (rng or random).choice(others)
        case AssignmentType.least_done:
            # Fewest completions of this chore. A tie that includes the person on the hook is
            # a handover: they are dropped and it goes to the alphabetically first of the
            # others. Only a tie, though - somebody genuinely behind keeps the chore while
            # they catch up, which is why this is not `random`'s blanket exclusion of
            # `current` above. A plain `min` over the ordered pool is what this used to be,
            # and it re-picked whoever sorted first, so two people level meant the one who
            # had just finished kept it (issue #58).
            ordered = _ordered(pool)
            fewest = min(counts.get(u.id, 0) for u in ordered)
            tied = [u for u in ordered if counts.get(u.id, 0) == fewest]
            return next((u for u in tied if u.id != current.id), tied[0])
        case _:  # pragma: no cover - all non-manual strategies handled above
            return current


def should_reassign(done_count: int, turn_length: int) -> bool:
    """Whether a handoff happens after the `done_count`-th completion (1-based: callers
    pass the running completion count, >= 1). `turn_length` is how many completions one
    person holds before handing off (1 = every completion), so reassign on each multiple
    of the turn length. `turn_length` is clamped to >= 1 to stay safe on bad input."""
    return done_count % max(turn_length, 1) == 0
