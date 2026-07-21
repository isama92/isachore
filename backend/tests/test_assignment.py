import random

from app.core.assignment import initial_assignee, next_assignee, should_reassign
from app.models import AssignmentType, User


def _user(id_: int, first: str, last: str = "X") -> User:
    # An unpersisted User is enough to exercise the pure assignment logic.
    return User(id=id_, first_name=first, last_name=last)


ALICE = _user(1, "Alice")
BOB = _user(2, "Bob")
CARA = _user(3, "Cara")


# --- initial_assignee -------------------------------------------------------


def test_initial_empty_pool_is_none() -> None:
    assert initial_assignee(AssignmentType.alphabetical, []) is None


def test_initial_single_member_pool_is_that_member_for_every_strategy() -> None:
    for strategy in AssignmentType:
        assert initial_assignee(strategy, [BOB]) is BOB


def test_initial_alphabetical_and_least_done_pick_first_by_name() -> None:
    pool = [CARA, ALICE, BOB]
    assert initial_assignee(AssignmentType.alphabetical, pool) is ALICE
    assert initial_assignee(AssignmentType.least_done, pool) is ALICE


def test_initial_manual_multiple_is_none() -> None:
    assert initial_assignee(AssignmentType.manual, [ALICE, BOB]) is None


def test_initial_random_is_deterministic_with_a_seeded_rng() -> None:
    pool = [ALICE, BOB, CARA]
    pick = initial_assignee(AssignmentType.random, pool, rng=random.Random(0))
    assert pick in pool
    assert initial_assignee(AssignmentType.random, pool, rng=random.Random(0)) is pick


# --- next_assignee ----------------------------------------------------------


def test_next_alphabetical_wraps() -> None:
    pool = [ALICE, BOB, CARA]
    assert next_assignee(AssignmentType.alphabetical, pool, ALICE, {}) is BOB
    assert next_assignee(AssignmentType.alphabetical, pool, BOB, {}) is CARA
    assert next_assignee(AssignmentType.alphabetical, pool, CARA, {}) is ALICE  # wraps


def test_next_manual_keeps_the_current_assignee() -> None:
    assert next_assignee(AssignmentType.manual, [ALICE, BOB], ALICE, {}) is ALICE


def test_next_manual_does_not_self_heal_a_dropped_current() -> None:
    # Deliberate: manual never auto-rotates, so a completion keeps the current assignee
    # even when the pool was edited to drop them. update_chore reconciles pool edits.
    assert next_assignee(AssignmentType.manual, [ALICE, BOB], CARA, {}) is CARA


def test_next_manual_multi_member_without_a_current_stays_unassigned() -> None:
    # A brand-new manual multi-member chore (initial pick was None): a completion
    # does not invent an assignee.
    assert next_assignee(AssignmentType.manual, [ALICE, BOB], None, {}) is None


def test_next_least_done_picks_the_fewest_completions() -> None:
    pool = [ALICE, BOB, CARA]
    counts = {ALICE.id: 3, BOB.id: 1, CARA.id: 2}
    assert next_assignee(AssignmentType.least_done, pool, ALICE, counts) is BOB


def test_next_least_done_breaks_ties_alphabetically() -> None:
    pool = [CARA, BOB, ALICE]
    assert next_assignee(AssignmentType.least_done, pool, CARA, {}) is ALICE  # all zero


def test_next_least_done_rotates_with_post_completion_counts() -> None:
    # counts include the just-recorded completion: Alice just finished, so she is no
    # longer least-done and the turn moves to Bob; once Bob catches up the tie breaks
    # back to Alice alphabetically.
    pool = [ALICE, BOB]
    assert next_assignee(AssignmentType.least_done, pool, ALICE, {ALICE.id: 1, BOB.id: 0}) is BOB
    assert next_assignee(AssignmentType.least_done, pool, BOB, {ALICE.id: 1, BOB.id: 1}) is ALICE


def test_next_random_excludes_the_current_assignee() -> None:
    # With two members the only other choice is Bob, whatever the rng draws.
    pick = next_assignee(AssignmentType.random, [ALICE, BOB], ALICE, {}, rng=random.Random(0))
    assert pick is BOB


def test_next_random_excludes_current_from_a_larger_pool() -> None:
    # With three members, the current one is genuinely excluded from the choice set.
    pool = [ALICE, BOB, CARA]
    for seed in range(10):
        pick = next_assignee(AssignmentType.random, pool, BOB, {}, rng=random.Random(seed))
        assert pick is not BOB
        assert pick in pool


def test_next_current_not_in_pool_falls_back_to_initial() -> None:
    assert next_assignee(AssignmentType.alphabetical, [ALICE, BOB], CARA, {}) is ALICE


def test_next_current_none_falls_back_to_initial() -> None:
    assert next_assignee(AssignmentType.alphabetical, [BOB, ALICE], None, {}) is ALICE


def test_next_single_member_pool_keeps_member() -> None:
    assert next_assignee(AssignmentType.random, [ALICE], ALICE, {}) is ALICE


def test_next_empty_pool_is_none() -> None:
    assert next_assignee(AssignmentType.alphabetical, [], None, {}) is None


# --- should_reassign --------------------------------------------------------


def test_should_reassign_every_completion_when_turn_length_one() -> None:
    assert all(should_reassign(n, 1) for n in range(1, 6))


def test_should_reassign_every_n_when_take_turns() -> None:
    assert [should_reassign(n, 3) for n in range(1, 7)] == [False, False, True, False, False, True]


def test_should_reassign_clamps_non_positive_turn_length() -> None:
    assert should_reassign(1, 0) is True


def test_should_reassign_zero_count_is_true_but_not_relied_on() -> None:
    # done_count is 1-based in practice; this just pins the raw modulo behaviour.
    assert should_reassign(0, 3) is True
