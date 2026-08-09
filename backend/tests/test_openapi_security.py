"""What the generated document says about who may call what.

`test_openapi_spec.py` proves the committed YAML still matches the app. This proves the app
still describes its own gates, which is a different failure: a route can be perfectly
protected and publish itself as anonymous, and that is exactly the state the whole API was in
before `app/api/responses.py` existed.

Three of these are deliberately **closed sets** rather than spot checks. A gate is added by
writing one word into a decorator and lost by deleting it, neither of which any other test
notices, so the useful assertion is "these and no others" - the same shape as
`test_csrf.py`'s `_AUTH_COOKIES` tuple and `test_every_role_is_on_the_ladder`. They cost an
edit whenever a route is added, and that edit is the review prompt they exist to force.
"""

import ast
from pathlib import Path
from typing import Any

from app.main import app

# Read once: app.openapi() memoises, but the whole module wants the same document anyway.
SPEC = app.openapi()

# The routes anybody can reach with no session at all. Everything else is gated.
PUBLIC_OPERATIONS = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/auth/methods"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/verify-2fa"),
    ("GET", "/api/v1/auth/oidc/start"),
    ("GET", "/api/v1/auth/oidc/callback"),
    ("GET", "/api/v1/confirm/{token}"),
    ("POST", "/api/v1/confirm/{token}"),
    ("GET", "/api/v1/invitations/{token}"),
}

# The household-scoped routes that reach `core/households.py`'s require_role, or an
# organiser check standing in for it (`_get_organised_household`), or hand-raise the same
# refusal as undo_completion does.
ROLE_GATED_OPERATIONS = {
    ("POST", "/api/v1/chores"),
    ("PATCH", "/api/v1/chores/{chore_id}"),
    ("DELETE", "/api/v1/chores/{chore_id}"),
    ("POST", "/api/v1/tags"),
    ("GET", "/api/v1/tags/{tag_id}"),
    ("PATCH", "/api/v1/tags/{tag_id}"),
    ("DELETE", "/api/v1/tags/{tag_id}"),
    ("DELETE", "/api/v1/completions/{completion_id}"),
    ("GET", "/api/v1/households/{household_id}/invitations"),
    ("POST", "/api/v1/households/{household_id}/invitations"),
    ("POST", "/api/v1/households/{household_id}/invitations/{invitation_id}/revoke"),
    ("DELETE", "/api/v1/households/{household_id}/invitations/{invitation_id}"),
}

# Kept apart from the set above because they are a DIFFERENT refusal wearing the same status
# code: `_get_owned_household`, which turns away an organiser who does not own the household
# and which no role change can clear. Ownership is off the ladder (see CLAUDE.md on
# RequireOwner), so folding these in would publish "ask for a stronger role" on three routes
# where that advice is useless.
OWNER_GATED_OPERATIONS = {
    ("PATCH", "/api/v1/households/{household_id}"),
    ("DELETE", "/api/v1/households/{household_id}"),
    ("DELETE", "/api/v1/households/{household_id}/members/{user_id}"),
}

# Setting a member's role refuses both ways in one handler - organiser for the change
# itself, ownership for anything involving the organiser role - so it belongs to neither set
# above and carries a description covering both branches.
BOTH_GATES_OPERATIONS = {
    ("PATCH", "/api/v1/households/{household_id}/members/{user_id}"),
}

# Every route behind a core/rate_limit.py counter. Hand-written like the sets above, but
# unlike them it has a derived counterpart below - this one was written with four entries
# and the fifth, the test-email cooldown, went unnoticed precisely because a closed set
# compared against the document passes when BOTH sides omit something.
THROTTLED_OPERATIONS = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/verify-2fa"),
    ("GET", "/api/v1/auth/oidc/start"),
    ("GET", "/api/v1/auth/oidc/callback"),
    ("POST", "/api/v1/admin/settings/test-email"),
}

ROUTERS_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "v1"


def _operations() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in SPEC["paths"].items()
        for method, operation in item.items()
    }


# Derived once, like SPEC: every test below walks it, and the 429 test walks it per entry.
OPERATIONS = _operations()


def declaring(code: str) -> set[tuple[str, str]]:
    return {key for key, op in OPERATIONS.items() if code in op["responses"]}


def handlers_calling(prefix: str) -> set[str]:
    """Names of the route handlers in api/v1 whose body calls a function starting with
    `prefix`, read from the source with `ast`.

    This is the antidote to a hand-written closed set that is only closed against the
    document: comparing one list of paths with another passes happily when both sides are
    missing the same route, which is exactly how the test-email cooldown stayed undocumented.
    Reading the *call sites* instead means a new throttle shows up whether or not anybody
    remembered this file.
    """
    found: set[str] = set()
    for module in ROUTERS_DIR.glob("*.py"):
        for node in ast.parse(module.read_text()).body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            decorated = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and getattr(d.func.value, "id", "") == "router"
                for d in node.decorator_list
            )
            if not decorated:
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id.startswith(prefix)
                ):
                    found.add(node.name)
    return found


def handler_name(key: tuple[str, str]) -> str:
    """The endpoint function behind an operation. FastAPI builds the default operationId as
    `{function}_{path}_{method}`, and every path here carries the /api/v1 prefix."""
    return OPERATIONS[key]["operationId"].split("_api_v1_")[0]


def test_the_security_schemes_are_exactly_the_three_transports() -> None:
    """Closed, because the omission is the interesting part.

    X-CSRF-Token is absent on purpose: FastAPI emits one `security` entry per scheme and
    OpenAPI reads separate entries as ALTERNATIVES, so a `csrfToken` scheme would publish
    "session cookie or CSRF header" where core/csrf.py requires both. It is described in
    prose on the app instead (main.py's API_DESCRIPTION). Nothing in the app's behaviour can
    tell the difference, so this assertion is the only thing standing between that reasoning
    and somebody adding the scheme because it looks missing.
    """
    assert set(SPEC["components"]["securitySchemes"]) == {
        "sessionCookie",
        "bearerToken",
        "parkedAdminCookie",
    }
    assert "X-CSRF-Token" in SPEC["info"]["description"]


def test_a_gated_operation_and_a_401_are_the_same_thing() -> None:
    """Both directions, in one assertion.

    `security` comes from the dependency tree and the 401 comes from a hand-written
    `responses=`, so the two drift apart in opposite ways: a new gated route added to a
    router that carries no block declares no 401, and a block placed on a public router
    declares a 401 nothing can raise. Comparing the two sets catches either.

    **This equality is stronger than the API is, and will have to be relaxed once.** Two
    PUBLIC operations can genuinely answer 401 - `POST /auth/login` on bad credentials, and
    `POST /auth/verify-2fa` with no challenge cookie - and documenting those is the first
    item on README's remaining todo list. When that lands, this becomes `gated <= 401` plus
    an explicit allow-list of public-but-401 operations. That is an expected edit, not a
    guard being deleted; it is written down here because a green equality assertion
    otherwise reads as an invariant and the todo reads as forbidden.
    """
    assert {key for key, op in OPERATIONS.items() if op.get("security")} == declaring("401")


def test_the_public_operations_are_exactly_these() -> None:
    """The `auth` and `invitations` routers each mix public routes with gated ones, so no
    include_router block can be right for them and every gate there is hand-declared. This is
    what notices when a hand-declared one is forgotten."""
    anonymous = {key for key, op in OPERATIONS.items() if not op.get("security")}
    assert anonymous == PUBLIC_OPERATIONS


def test_every_admin_operation_declares_a_403() -> None:
    admin = {key for key in OPERATIONS if key[1].startswith("/api/v1/admin/")}
    assert admin, "no admin operations found; the /admin prefix rule has moved"
    assert admin <= declaring("403")


def test_a_403_is_declared_only_where_a_gate_can_raise_one() -> None:
    """Closed for the same reason as the scheme set, and it is the assertion that keeps the
    role blocks honest in the *other* direction: declaring FORBIDDEN_ROLE on the four
    household routers wholesale would put a 403 on `POST /households`, which any
    authenticated user may call, and on `GET /completions/filters`, which is deliberately not
    role-narrowed at all.

    Note what this does NOT cover, because the status code is shared and the set is not:
    CsrfProtectMiddleware also answers 403, on any cookie-authenticated unsafe method with no
    X-CSRF-Token, which is roughly two dozen operations here including several in neither set
    below. That refusal is deliberately left to prose in main.py's API_DESCRIPTION - it is a
    property of the transport rather than of any route, and documenting it per operation
    would bury the two gates this test is about.
    """
    non_admin = {key for key in declaring("403") if not key[1].startswith("/api/v1/admin/")}
    assert non_admin == ROLE_GATED_OPERATIONS | OWNER_GATED_OPERATIONS | BOTH_GATES_OPERATIONS


def test_the_owner_gate_and_the_role_gate_say_different_things() -> None:
    """The gates share a status code and would read as interchangeable. They are not: a role
    403 tells the caller a promotion would help and an ownership 403 tells them it would not,
    so swapping the blocks is a silent documentation bug that no status-code check finds.

    Asserting the ABSENCE of the other gate's wording is what makes this bite. Checking only
    that an owner-gated route says "owner" passed happily while one route said "role" and
    meant ownership, because a description can contain both words while describing one gate.

    The discriminator is "role held", not "role", and that is the second version of this
    test: FORBIDDEN_OWNER's own text contains the word "role" (in "no role change grants
    it"), so a bare `"role" in description` let FORBIDDEN_OWNER stand in for the combined
    block - publishing "only the owner may do this" on a route an organiser may legitimately
    call. Only the two role blocks say "role held", so the three sets are now mutually
    exclusive and every swap between them fails.
    """
    for key in OWNER_GATED_OPERATIONS:
        description = OPERATIONS[key]["responses"]["403"]["description"].lower()
        assert "owner" in description and "role held" not in description, key
    for key in ROLE_GATED_OPERATIONS:
        description = OPERATIONS[key]["responses"]["403"]["description"].lower()
        assert "role held" in description and "owner" not in description, key
    for key in BOTH_GATES_OPERATIONS:
        description = OPERATIONS[key]["responses"]["403"]["description"].lower()
        assert "owner" in description and "role held" in description, key


def test_the_throttled_operations_declare_a_429_carrying_retry_after() -> None:
    assert declaring("429") == THROTTLED_OPERATIONS
    for key in THROTTLED_OPERATIONS:
        headers = OPERATIONS[key]["responses"]["429"]["headers"]
        assert "Retry-After" in headers, key


def test_every_handler_behind_a_throttle_declares_a_429() -> None:
    """The derived half, and the one that would have caught the miss.

    The set above compares two hand-maintained lists of paths, so it passes when both omit
    the same route. This reads the `enforce_*` call sites out of the router sources instead,
    so adding a throttle to a handler and forgetting its `responses=` fails here even though
    nobody touched this file.
    """
    assert handlers_calling("enforce_") == {handler_name(key) for key in THROTTLED_OPERATIONS}


def test_every_declared_refusal_carries_its_explanation() -> None:
    """A refusal declared with a `description` and no `model` publishes itself as bodyless,
    which is wrong for every hand-raised HTTPException in this app: they all answer in
    ErrorDetail's shape. Cheap to get wrong, since the description alone reads complete."""
    for key, op in OPERATIONS.items():
        for code in ("401", "403", "429"):
            response = op["responses"].get(code)
            if response is None:
                continue
            schema = response.get("content", {}).get("application/json", {}).get("schema", {})
            assert schema.get("$ref", "").endswith("/ErrorDetail"), (code, key)
