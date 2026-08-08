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


def test_initial_least_done_ranks_on_the_counts_when_it_is_given_them() -> None:
    # Bob and Cara are both on zero, so the tie falls to Bob by name - Alice is out of it
    # despite sorting first, which is the whole point of passing a tally.
    pool = [CARA, ALICE, BOB]
    assert initial_assignee(AssignmentType.least_done, pool, counts={ALICE.id: 3}) is BOB


def test_initial_least_done_without_counts_gives_the_old_alphabetical_answer() -> None:
    # The identity `create_chore`, `db/seed.py` and the `make_chore` fixture all lean on:
    # every key reads 0, so `min` returns the first of `_ordered`. If this ever stops
    # holding, those three call sites need a tally they currently have nothing to build.
    pool = [CARA, ALICE, BOB]
    assert initial_assignee(AssignmentType.least_done, pool) is ALICE
    assert initial_assignee(AssignmentType.least_done, pool, counts={}) is ALICE


def test_initial_alphabetical_ignores_the_counts() -> None:
    # Pins the arm split: only least_done reads the tally, so a chore that says
    # "alphabetical" still starts with Alice however much she has already done.
    pool = [CARA, ALICE, BOB]
    assert initial_assignee(AssignmentType.alphabetical, pool, counts={ALICE.id: 9}) is ALICE


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


def test_next_least_done_breaks_ties_by_name_among_the_others() -> None:
    # All zero, so everyone is tied: Cara is on the hook and therefore dropped, and the
    # remaining tie falls to Alice by name. Note this case passes under the pre-#58 rule
    # too, because Cara sorts last and a plain `min` was already skipping her.
    pool = [CARA, BOB, ALICE]
    assert next_assignee(AssignmentType.least_done, pool, CARA, {}) is ALICE


def test_next_least_done_rotates_with_post_completion_counts() -> None:
    # counts include the just-recorded completion: Alice just finished, so she is no
    # longer least-done and the turn moves to Bob; once Bob draws level the tie hands
    # back to Alice, the only other member of it.
    pool = [ALICE, BOB]
    assert next_assignee(AssignmentType.least_done, pool, ALICE, {ALICE.id: 1, BOB.id: 0}) is BOB
    assert next_assignee(AssignmentType.least_done, pool, BOB, {ALICE.id: 1, BOB.id: 1}) is ALICE


def test_next_least_done_hands_over_when_the_person_on_the_hook_ties() -> None:
    # Issue #58, and the case the two above cannot catch: the current assignee has to be the
    # alphabetically FIRST member for the old rule to bite. With Alice up and Bob drawing
    # level, `min(_ordered(pool), ...)` handed the chore straight back to her - the reported
    # "it kept being assigned to the same person". A tie is a handover.
    pool = [ALICE, BOB]
    assert next_assignee(AssignmentType.least_done, pool, ALICE, {ALICE.id: 1, BOB.id: 1}) is BOB


def test_next_least_done_keeps_whoever_is_genuinely_behind() -> None:
    # Only a TIE hands over. Somebody still short of the others keeps the chore while they
    # catch up, which is what stops the fix collapsing into `random`'s blanket exclusion of
    # the current assignee - that would make least_done just alphabetical with extra steps.
    pool = [ALICE, BOB]
    assert next_assignee(AssignmentType.least_done, pool, ALICE, {ALICE.id: 1, BOB.id: 5}) is ALICE


def test_next_least_done_drops_only_the_person_on_the_hook_from_the_tie() -> None:
    pool = [CARA, BOB, ALICE]
    # All three level with Alice up: she is dropped and it moves on by name, not back to her.
    level = {ALICE.id: 2, BOB.id: 2, CARA.id: 2}
    assert next_assignee(AssignmentType.least_done, pool, ALICE, level) is BOB
    # The tie is taken at the minimum, not across the pool: Alice is well ahead, so she is not
    # in it at all and cannot win it by name. Bob is up, which leaves Cara.
    ahead = {ALICE.id: 5, BOB.id: 2, CARA.id: 2}
    assert next_assignee(AssignmentType.least_done, pool, BOB, ahead) is CARA


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


def test_next_least_done_fallback_still_ranks_on_the_counts() -> None:
    # The fallback hands `counts` on rather than dropping them. An unassigned chore ("nobody
    # in particular") lands here on every turn boundary, so without that it would quietly
    # answer alphabetically - Alice, who has already done it - for as long as nobody is up.
    assert next_assignee(AssignmentType.least_done, [ALICE, BOB], None, {ALICE.id: 1}) is BOB


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
