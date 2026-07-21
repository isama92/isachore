"""Pure, DB-free assignment logic: pick who is on the hook for a chore occurrence.

Mirrors app/core/chores.py - no database access. Callers resolve the assignee pool
(a list of User) and pass it in, along with the current assignee and, for
`least_done`, a per-user completion-count map. The chore's `assignment_type` decides
who comes next:

- manual:       never auto-rotates; the caller sets the assignee by hand.
- alphabetical: the pool ordered by (first_name, last_name, id); the next one, wrapping.
- least_done:   the pool member with the fewest completions of this chore (ties by name).
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
    strategy: AssignmentType, pool: list[User], *, rng: random.Random | None = None
) -> User | None:
    """Who is on the hook for a chore's first occurrence. A single-member pool is
    always that member; an empty pool is unassigned (shared). `manual` with more than
    one member returns None so the caller can set the current assignee by hand."""
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
        case _:  # alphabetical / least_done: first alphabetically
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
    (post-completion snapshot); otherwise the person who just finished still ties as
    least-done and gets re-picked, so a `least_done` chore would never rotate."""
    if strategy == AssignmentType.manual:
        return current  # never auto-rotates; update_chore keeps it valid
    if not pool:
        return None
    if not _in_pool(current, pool):
        # No current yet, or the pool was edited to drop them: start fresh.
        return initial_assignee(strategy, pool, rng=rng)
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
            # Fewest completions of this chore; ties broken by alphabetical order.
            return min(_ordered(pool), key=lambda u: counts.get(u.id, 0))
        case _:  # pragma: no cover - all non-manual strategies handled above
            return current


def should_reassign(done_count: int, turn_length: int) -> bool:
    """Whether a handoff happens after the `done_count`-th completion (1-based: callers
    pass the running completion count, >= 1). `turn_length` is how many completions one
    person holds before handing off (1 = every completion), so reassign on each multiple
    of the turn length. `turn_length` is clamped to >= 1 to stay safe on bad input."""
    return done_count % max(turn_length, 1) == 0
