"""The refusals every gated route shares, written down once.

`Depends` carries no `responses`, so an auth or role gate contributes nothing to the OpenAPI
document however many routes it protects. Before these blocks existed not one of the 72
operations declared a 401 or a 403, which made `docs/api/openapi.yaml` describe a gated API
as though every route answered anonymously.

They are applied at the `include_router` calls in `api/v1/router.py`, which merge them into
every route of that router (a route's own `responses` still wins). The grouping there is
therefore what decides which refusals an operation claims, so a router that mixes public and
gated routes must declare per route instead - see the note at the bottom of that module.

Only the CROSS-CUTTING refusals get a named block here: the ones a shared gate raises rather
than a handler. A 404 for a missing chore or a 409 on a duplicate tag is a property of that
one endpoint, so it is written at that endpoint, with `refusals()` below.

**A description has to cover every branch that produces its status code, not the first one
you find.** Many of these codes have several: `POST /admin/users` answers 400 for a missing
password *or* unconfigured SMTP, and `PATCH /chores/{id}` answers 400 for a bad assignee *or*
a bad tag *or* a current assignee outside the pool. Naming one of them reads as complete and
is worse than saying nothing, because a client author has no way to discover the rest.

The first draft of this paragraph illustrated the rule with a claim that was itself false -
that the same chore route answers 404 for a missing household or tag, when both are 400s -
which is as good a demonstration as any of why the sentence is the part to check.
`tests/test_openapi_refusals.py` checks that each code is declared and that none is declared
spuriously; it cannot check that the sentence is true, so that part is on the writer.

TWO cross-cutting refusals are deliberately absent, and they are the ones most likely to be
"noticed missing". Both answer 403, both are a property of the CREDENTIAL or the transport
rather than of any route, and both are stated once in `main.py`'s `API_DESCRIPTION` instead
of being stamped onto most of the document, where they would bury the gate refusals these
blocks exist to make visible:

- `CsrfProtectMiddleware`, on a cookie-authenticated unsafe method with no `X-CSRF-Token`.
  Roughly two dozen operations across every router, public ones included.
- `get_current_user`, when a personal access token is presented to a gated operation outside
  the `apiToken` allowlist - which is most of the gated document.

Neither is visible to `tests/test_openapi_refusals.py` (one is middleware, the other a
dependency), so declaring either per route fails that file rather than satisfying it.
"""

from typing import Any

from fastapi import status

from app.schemas import ErrorDetail

Responses = dict[int | str, dict[str, Any]]


def refusals(*entries: tuple[int, str]) -> Responses:
    """A route's own refusals, as `(status, description)` pairs.

    Every one of them answers in `ErrorDetail`'s shape - that is what a hand-raised
    `HTTPException` produces - so this fills the `model` in rather than leaving each route to
    remember it. A block with only a `description` publishes itself as bodyless, which is
    wrong for every refusal in this API.

    Compose with the gate blocks where a route has both: `FORBIDDEN_ROLE | refusals(...)`.

    Passing the same status twice raises rather than silently keeping the last one. That is
    not a hypothetical slip: the paragraph above tells you to cover every branch, and writing
    one entry per branch is the obvious way to do it - which a plain dict comprehension would
    answer by publishing only the final sentence, with no test able to notice. Put the
    branches in ONE description instead.
    """
    seen = [code for code, _ in entries]
    duplicated = {code for code in seen if seen.count(code) > 1}
    if duplicated:
        raise ValueError(
            f"refusals() got {sorted(duplicated)} more than once. One entry per status code: "
            "put every branch that produces it into a single description."
        )
    return {
        status_code: {"model": ErrorDetail, "description": text} for status_code, text in entries
    }


UNAUTHORISED: Responses = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorDetail,
        "description": (
            "No usable session: the cookie or bearer token is absent, expired, or belongs to "
            "a user who is no longer active."
        ),
    }
}

FORBIDDEN_ADMIN: Responses = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorDetail,
        "description": "Signed in, but not a site administrator.",
    }
}

# Distinct from FORBIDDEN_ADMIN because the two answer different questions: this one is
# core/households.py's require_role, which the caller can clear by being given a stronger
# role in that household. Note the 404 counterpart is NOT here - an invisible household is a
# per-endpoint answer, and which of the two a route gives is exactly the distinction that
# module's docstring draws.
FORBIDDEN_ROLE: Responses = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorDetail,
        "description": (
            "A member of the household, but the role held there does not reach what this "
            "route requires."
        ),
    }
}

# A THIRD 403, and it is not a stronger rung of the one above: ownership is off the ladder
# entirely (see CLAUDE.md on RequireOwner). `_get_owned_household` refuses an *organiser*
# who does not own the household, and no role change clears that - only a transfer does. So
# documenting these routes with FORBIDDEN_ROLE would tell a reader to ask for a promotion
# that cannot help them.
FORBIDDEN_OWNER: Responses = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorDetail,
        "description": (
            "Only the household's owner may do this. Being an organiser is not enough, and "
            "no role change grants it - ownership has to be transferred."
        ),
    }
}

# One route refuses BOTH ways and so can take neither block: setting a member's role needs
# organiser (the ladder), but *granting* organiser, or touching a row that already holds it,
# needs ownership. Publishing either block alone would be half true, and the half it left
# out is the one a reader would act on - organiser is already the top rung, so "obtain a
# stronger role" is advice nobody can follow.
FORBIDDEN_ROLE_OR_OWNER: Responses = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorDetail,
        "description": (
            "Either the role held in this household does not reach organiser, or the change "
            "involves the organiser role itself, which only the household's owner may grant "
            "or alter. The second cannot be cleared by a promotion, only by a transfer."
        ),
    }
}

THROTTLED: Responses = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorDetail,
        "description": "Too many attempts. `Retry-After` carries the seconds still to run.",
        "headers": {
            "Retry-After": {
                "description": "Seconds until the throttle window clears.",
                "schema": {"type": "integer"},
            }
        },
    }
}
