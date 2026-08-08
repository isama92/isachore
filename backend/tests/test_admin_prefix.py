"""The one rule about where routes live: `AdminUser` and `/api/v1/admin` imply each other.

Written down in `api/v1/router.py` and in CLAUDE.md, and until this file existed it was
prose checked by hand. Nothing else catches a breach: ruff does not, the endpoint suites do
not, and `test_openapi_spec.py` compares the committed document to whatever the app
currently produces, so it accepts a new admin router on the wrong prefix the moment somebody
regenerates the spec. The rule would have decayed back into the accident it was before.

Both directions matter and fail differently. A gated route outside `/admin` is a path that
lies about who it serves, which is what this whole move was for. An ungated route *inside*
`/admin` is worse: the prefix reads as a promise, and a reviewer skimming a diff will take
it for one.
"""

from fastapi.routing import APIRoute

from app.api.deps import require_admin
from app.api.v1.router import api_router

PREFIX = "/api/v1"
ADMIN = f"{PREFIX}/admin"

# Two routes that read like admin surfaces and are gated on something else. Neither is
# `require_admin`-gated, which is the whole point, so subtracting this set below removes
# nothing today - it is there so that the day one of them DOES acquire an AdminUser gate,
# the failure comes from the second test, which names the route and says where it belongs,
# rather than from the first, which would only report a set difference.
#
# - stop-impersonating takes NO user dependency and authenticates off the parked admin
#   cookie, checked inline. It has to: mid-impersonation the active session belongs to the
#   impersonated user, who is usually not an admin, so an AdminUser gate would turn away the
#   only caller it exists for.
# - /logs is CurrentUser-gated and scoped by household ownership, never by is_admin.
OFF_LADDER = {
    ("POST", f"{PREFIX}/auth/stop-impersonating"),
    ("GET", f"{PREFIX}/logs"),
}


def _depends_on(dependant: object, target: object) -> bool:
    """Whether `target` appears anywhere in a route's dependency tree."""
    return any(
        d.call is target or _depends_on(d, target) for d in getattr(dependant, "dependencies", [])
    )


def _is_gated(route: APIRoute, inherited: list) -> bool:
    """Admin-gated whether the dependency sits in the signature, on the route, on the
    router, or on the include_router call."""
    return _depends_on(route.dependant, require_admin) or any(
        getattr(d, "dependency", None) is require_admin for d in inherited
    )


def _routes() -> list[tuple[str, str, APIRoute, list]]:
    """Every (method, full path, route) the API serves.

    Walks the tree by hand because FastAPI 0.139+ registers included routers lazily: the
    entries in `api_router.routes` are `_IncludedRouter` wrappers holding the real router
    and its prefix, and `app.routes` does not contain them at all. `app.openapi()` would
    give the paths but not the dependencies, which is the half this test turns on.
    """

    def walk(router: object, prefix: str, inherited: list) -> list[tuple[str, APIRoute, list]]:
        found: list[tuple[str, APIRoute, list]] = []
        for route in getattr(router, "routes", []):
            if isinstance(route, APIRoute):
                found.append((prefix + route.path, route, inherited))
            elif hasattr(route, "original_router"):
                context = getattr(route, "include_context", None)
                # Dependencies passed to include_router are combined onto the *effective*
                # route, never onto the original this walk reads, so they have to be
                # carried down by hand. Nothing uses that form today; without this a
                # `include_router(logs.router, dependencies=[Depends(require_admin)])`
                # would be admin-gated outside /admin and pass silently, which is exactly
                # the direction the docstring above calls a path that lies.
                found += walk(
                    route.original_router,
                    prefix + getattr(context, "prefix", ""),
                    [*inherited, *getattr(context, "dependencies", [])],
                )
        return found

    return [
        (method, path, route, inherited)
        for path, route, inherited in walk(api_router, PREFIX, [])
        for method in route.methods
        if method not in ("HEAD", "OPTIONS")
    ]


def test_every_admin_gated_route_lives_under_admin() -> None:
    routes = _routes()
    # Guard the guard: a traversal that silently found nothing would make both assertions
    # below vacuously true, which is the failure mode of walking a lazily-built tree.
    assert len(routes) > 50, f"route walk found only {len(routes)}; the traversal is broken"

    gated = {(m, p) for m, p, r, inh in routes if _is_gated(r, inh)}
    under = {(m, p) for m, p, r, inh in routes if p.startswith(f"{ADMIN}/") or p == ADMIN}

    assert gated, "no AdminUser-gated route found at all"
    assert gated - under - OFF_LADDER == set(), "AdminUser-gated but not under /api/v1/admin"
    assert under - gated == set(), "under /api/v1/admin but not AdminUser-gated"


def test_the_off_ladder_routes_still_exist_and_are_still_off_it() -> None:
    """This is what actually holds the two exemptions, rather than the subtraction above.

    A renamed or deleted route would leave an entry naming nothing, which is dead weight a
    reader would take for a live decision; and an entry that *became* admin-gated is the case
    the exemption must stop covering, since at that point it belongs under /admin like the
    other twenty.
    """
    routes = _routes()
    served = {(m, p) for m, p, _r, _i in routes}
    gated = {(m, p) for m, p, r, inh in routes if _is_gated(r, inh)}

    for exemption in OFF_LADDER:
        assert exemption in served, f"{exemption} no longer exists; drop it from OFF_LADDER"
        assert exemption not in gated, f"{exemption} is admin-gated now; it belongs under /admin"
