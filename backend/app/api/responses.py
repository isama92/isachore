"""The refusals every gated route shares, written down once.

`Depends` carries no `responses`, so an auth or role gate contributes nothing to the OpenAPI
document however many routes it protects. Before these blocks existed not one of the 72
operations declared a 401 or a 403, which made `docs/api/openapi.yaml` describe a gated API
as though every route answered anonymously.

They are applied at the `include_router` calls in `api/v1/router.py`, which merge them into
every route of that router (a route's own `responses` still wins). The grouping there is
therefore what decides which refusals an operation claims, so a router that mixes public and
gated routes must declare per route instead - see the note at the bottom of that module.

Only the CROSS-CUTTING refusals belong here: the ones a shared gate raises rather than a
handler. A 404 for a missing chore or a 409 on a duplicate tag is a property of that one
endpoint and stays on it.

One cross-cutting refusal is deliberately absent, and it is the one most likely to be
"noticed missing": `CsrfProtectMiddleware`'s 403 on a cookie-authenticated unsafe method
with no `X-CSRF-Token`. It applies to roughly two dozen operations across every router,
public ones included, and it is a property of the transport rather than of any route - so
it is stated once in `main.py`'s `API_DESCRIPTION` instead of being stamped onto half the
document, where it would bury the gate refusals these blocks exist to make visible.
"""

from typing import Any

from fastapi import status

from app.schemas import ErrorDetail

Responses = dict[int | str, dict[str, Any]]

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
