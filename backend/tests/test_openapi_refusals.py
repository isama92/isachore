"""Every refusal a route can raise is declared, and nothing else is.

`test_openapi_security.py` covers the refusals a shared *gate* produces - the 401, the two
403s, the 429 - and does it with hand-written closed sets, because a gate is applied in one
place and there are few of them. The refusals in this module are the other kind: raised by a
handler, or by a helper only that handler calls, and there are 87 of them across 53
operations. A hand-written list of that size is a list nobody maintains.

So this reads the code instead. For each route handler it walks the call graph, collects the
status codes reachable from it, and compares that with what the operation declares. Both
directions matter and for different reasons:

- **undeclared** is the original defect - a client generated from the spec believes a missing
  chore or a duplicate tag cannot happen;
- **declared but unreachable** is the same lie pointing the other way, and it is the easier
  one to commit, because copying a `responses=` block onto a neighbouring route is a one-line
  edit that no status-code check would notice.

The walker is a heuristic and says so. Where it is wrong, `UNREACHABLE` below records why,
one entry at a time. What must never happen is silencing an over-report by declaring the
refusal instead: that trades a failing test for a lying document, which is the whole thing
this file exists to prevent.
"""

import ast
import re
from pathlib import Path

from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
ROUTERS = BACKEND / "app" / "api" / "v1"

# Everywhere a handler's helpers can live. `core/` holds the shared refusals (require_role's
# 403, get_current_household's 404, the rate limiter's 429) and deps.py the 401 - but the
# ROUTERS are in here too, and leaving them out is what made a first version of this walker
# under-report. Routers import from each other: `admin_households.py` gets both
# `load_household_read` and `set_member_role` from `households.py`, so walking with only
# core/ and deps.py in scope reported `GET /admin/households/{id}` as raising nothing at all
# and missed the owner-row 409 on its member PATCH. Under-reporting is the direction that
# lets a missing declaration through, so the symbol table has to span everything a handler
# can reach.
#
# Names do collide across these files - eight route handlers share a name between
# `households.py` and `admin_households.py`. It does not matter here, because the module
# being walked is layered on top of this table so its own definitions win, and because the
# colliding names are entry points that no helper calls.
SHARED = [
    *sorted((BACKEND / "app" / "core").glob("*.py")),
    *sorted((BACKEND / "app" / "api" / "v1").glob("*.py")),
    BACKEND / "app" / "api" / "deps.py",
]

# FastAPI adds this to any operation taking parameters and it cannot be removed per route, so
# it is not a raise site and is excluded from both sides of every comparison below.
#
# **The exclusion is a blind spot, and nothing occupies it - keep it that way.** A
# hand-raised 422 would be invisible here in both directions, and it would also be
# undocumentable: FastAPI owns that code for pydantic's `HTTPValidationError` array, so a
# route answering it with an `ErrorDetail` string publishes one shape and sends another.
# `set_household_admin` did exactly that until it moved to 400, which is what
# `_resolve_assignees` already answered for the identical complaint. `grep HTTP_422` should
# find main.py's handler and nothing else; if it ever finds a raise, move that raise rather
# than reaching for a per-route `responses[422]`.
AUTO_VALIDATION = "422"

# Codes the walker reports for a route that genuinely cannot answer with them. Every entry
# needs its reason here, in this file, next to the entry - an unexplained one is how a guard
# like this rots into a list people append to until it means nothing.
#
# Note what an entry is NOT for: silencing a report you have not understood. The other way to
# make the guard quiet is to declare the refusal, and that is strictly worse - it swaps a red
# test for a document that lies to every client author who reads it.
UNREACHABLE: dict[tuple[str, str], dict[str, str]] = {
    ("POST", "/api/v1/households"): {
        "404": (
            "Both create routes hand the household they have just inserted to "
            "`load_household_read`, whose 404 is for a household that does not exist. This "
            "one does, by construction, in the same transaction."
        )
    },
    ("POST", "/api/v1/admin/households"): {
        "404": "Same as POST /households: the row was created immediately above the read."
    },
}


def _status_codes(source: str) -> set[str]:
    """The literal HTTP status codes named in a chunk of source.

    Four spellings, because under-reporting is the direction that lets a missing declaration
    through, and each of these is either already in the codebase or one keystroke away:

    - `status.HTTP_404_NOT_FOUND` - what every route here writes today;
    - a bare integer, `JSONResponse(status_code=503, ...)` - `api/v1/health.py` picks its
      branch that way, and reading only the qualified form made the guard report health's
      declared 503 as unreachable;
    - the constant imported bare, `status_code=HTTP_403_FORBIDDEN` - `core/csrf.py` and
      `core/body_limit.py` already do this;
    - the positional form, `HTTPException(404, "...")`, which is the commonest way to write
      one by hand and was invisible to the first version of this.

    Note this deliberately reads *responses the route can produce*, not only raises: a
    returned JSONResponse with a 4xx or 5xx is a refusal to the caller either way.
    """
    return (
        # Qualified or bare constant: `status.HTTP_404_NOT_FOUND`, `HTTP_404_NOT_FOUND`.
        set(re.findall(r"\bHTTP_(\d{3})_[A-Z_]+", source))
        # `status_code=404`
        | set(re.findall(r"\bstatus_code\s*=\s*(\d{3})\b", source))
        # `HTTPException(404, ...)` - positional, which no keyword pattern sees.
        | set(re.findall(r"\bHTTPException\(\s*(\d{3})\b", source))
    )


def _refusals(codes: set[str]) -> set[str]:
    """Only the 4xx and 5xx. A 200 or a 302 is an answer, not a refusal, and neither side of
    the comparison below should be counting them."""
    return {code for code in codes if code[0] in "45"} - {AUTO_VALIDATION}


def _module_symbols(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Every top-level function's source, and every module-level HTTPException constant's.

    The second half is not optional, and a first attempt at this walker did without it. Some
    handlers do not construct their refusal inline - `api/v1/invitations.py` raises a
    module-level `_invalid_token_exc`, `api/deps.py` a `_credentials_exc` - so following only
    *calls* silently missed those routes' 404 and 401. That is under-reporting: the guard
    would have passed while the document stayed wrong, which is worse than not having it.
    """
    source = path.read_text()
    functions: dict[str, str] = {}
    constants: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[node.name] = ast.get_source_segment(source, node) or ""
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            called = node.value.func
            if getattr(called, "id", "") == "HTTPException":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = ast.get_source_segment(source, node.value) or ""
    return functions, constants


def _shared_symbols() -> tuple[dict[str, str], dict[str, str]]:
    functions: dict[str, str] = {}
    constants: dict[str, str] = {}
    for path in SHARED:
        module_functions, module_constants = _module_symbols(path)
        functions.update(module_functions)
        constants.update(module_constants)
    return functions, constants


SHARED_FUNCTIONS, SHARED_CONSTANTS = _shared_symbols()


def _routes(path: Path) -> list[tuple[str, str, str]]:
    """(method, path suffix, handler name) for every `@router.<verb>` in a module."""
    source = path.read_text()
    found = []
    for node in ast.parse(source).body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and getattr(decorator.func.value, "id", "") == "router"
            ):
                suffix = decorator.args[0].value if decorator.args else ""
                found.append((decorator.func.attr.upper(), suffix, node.name))
    return found


def reachable_codes(module: Path) -> dict[str, set[str]]:
    """Handler name -> the status codes reachable from it, in one router module.

    A call graph plus a fixpoint, rather than a recursive descent per handler. The obvious
    recursion is exponential here: helpers are shared, so the same subtree is re-walked once
    per path that reaches it, and a `seen` set prevents cycles without preventing that. The
    first version of this took minutes on ~250 functions. This visits each edge once per
    round and settles in a handful of rounds.
    """
    functions, constants = _module_symbols(module)
    functions = {**SHARED_FUNCTIONS, **functions}
    constants = {**SHARED_CONSTANTS, **constants}

    direct: dict[str, set[str]] = {}
    callees: dict[str, set[str]] = {}
    for name, body in functions.items():
        codes = _status_codes(body)
        for constant, source in constants.items():
            if re.search(rf"\b{re.escape(constant)}\b", body):
                codes |= _status_codes(source)
        direct[name] = codes
        callees[name] = {
            other
            for other in functions
            if other != name and re.search(rf"\b{re.escape(other)}\s*\(", body)
        }

    reachable = {name: set(codes) for name, codes in direct.items()}
    changed = True
    while changed:
        changed = False
        for name, called in callees.items():
            before = len(reachable[name])
            for other in called:
                reachable[name] |= reachable[other]
            changed = changed or len(reachable[name]) != before

    return {handler: reachable[handler] for _, _, handler in _routes(module)}


SPEC = app.openapi()

DECLARED = {
    (method.upper(), path): _refusals(set(operation["responses"]))
    for path, item in SPEC["paths"].items()
    for method, operation in item.items()
}


def _prefixes() -> dict[str, str]:
    """Router module name -> the path prefix `router.py` mounts it under.

    Read from the source rather than matched by handler name, because handler names are NOT
    unique across modules: `households.py` and `admin_households.py` both define
    `delete_household`, `get_household`, `update_household_member` and five more. Keying the
    walk by handler name silently kept whichever module was read last and attributed its
    refusals to both routes - eight pairs of operations quietly compared against the wrong
    code. The prefix makes the path exact instead.
    """
    source = (ROUTERS / "router.py").read_text()
    found: dict[str, str] = {}
    for call in ast.walk(ast.parse(source)):
        if not (isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "include_router"):
            continue
        target = call.args[0] if call.args else None
        module = getattr(getattr(target, "value", None), "id", None)
        if module is None:
            continue
        prefix = ""
        for keyword in call.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                prefix = keyword.value.value
        found[module] = prefix
    return found


PREFIXES = _prefixes()
ROOT = "/api/v1"


def _walked() -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = {}
    for module in sorted(ROUTERS.glob("*.py")):
        if module.stem not in PREFIXES:
            continue  # router.py itself, and __init__.py
        codes_by_handler = reachable_codes(module)
        for method, suffix, handler in _routes(module):
            path = f"{ROOT}{PREFIXES[module.stem]}{suffix}"
            if (method, path) not in DECLARED:
                continue  # not in the schema, e.g. an include_in_schema=False asset route
            result[(method, path)] = _refusals(codes_by_handler[handler])
    return result


# Derived once: the walk is cheap now but every test wants the same answer.
WALKED = _walked()


def test_nothing_hand_raises_a_422() -> None:
    """The blind spot above, made executable instead of a `grep` in a comment.

    422 is excluded from both sides of every comparison in this file, because FastAPI adds
    one to any operation with parameters and it cannot be removed per route. So a
    hand-raised 422 is invisible here - and worse, undocumentable: that code already carries
    pydantic's `HTTPValidationError` array, so a route answering it with an `ErrorDetail`
    string publishes one shape and sends another. `set_household_admin` did exactly that
    until it moved to 400.

    A closed-set assertion rather than a behavioural one, for the same reason
    `test_csrf.py` pins `_AUTH_COOKIES` directly: nothing observable distinguishes the
    absence. If this fails, move the raise to the code that fits (400 for a bad reference,
    409 for a state conflict) rather than reaching for a per-route `responses[422]`.
    """
    offenders = [
        f"{path.relative_to(BACKEND)}:{number}"
        for path in sorted((BACKEND / "app").rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "HTTP_422" in line and path.name != "main.py"
    ]
    assert not offenders, (
        "a hand-raised 422 cannot be documented - the code belongs to pydantic's array-shaped "
        f"body. Use 400 for a bad reference or 409 for a state conflict: {offenders}"
    )


def test_every_unreachable_entry_is_still_needed() -> None:
    """An `UNREACHABLE` entry is subtracted forever, so a stale one is a hole nothing else
    reports: if the route later gains a genuine refusal with that code, the entry silences
    the requirement to declare it and no test fails. This makes an entry that no longer
    describes anything the walker sees fail instead of quietly staying."""
    for key, codes in UNREACHABLE.items():
        assert key in WALKED, f"{key} is no longer a route; drop its UNREACHABLE entry"
        for code, reason in codes.items():
            assert code in WALKED[key], (
                f"{key} no longer reaches {code}, so its UNREACHABLE entry is stale and is "
                f"now hiding any future one. Reason it carried: {reason}"
            )
            assert reason.strip(), f"{key} {code}: an UNREACHABLE entry needs its reason"


def test_the_walker_finds_something_to_walk() -> None:
    """A broken walker reports nothing reachable, which would make every assertion below pass
    vacuously - the failure mode where a guard is green because it is not running."""
    # Every operation in the schema, not merely most: a path the walk cannot map is a route
    # it silently stops checking, which is the failure this whole file is built to avoid.
    assert set(WALKED) == set(DECLARED)
    assert sum(len(codes) for codes in WALKED.values()) > 100

    # A route that raises nothing itself: its 404 comes from core/households.py, so this also
    # proves the walk crosses module boundaries rather than stopping at the file it started
    # in. Asserts on the WALK, not on what is declared - reading DECLARED here would make the
    # sanity check track the very work it is meant to be independent of.
    assert "404" in WALKED[("GET", f"{ROOT}/tags")]

    # The two names that collide across households.py and admin_households.py resolve to
    # different operations. Keyed by handler name they did not, and one silently shadowed the
    # other: the admin route's refusals were compared against the user route's declarations.
    assert (
        WALKED[("DELETE", f"{ROOT}/households/{{household_id}}")]
        != WALKED[("DELETE", f"{ROOT}/admin/households/{{household_id}}")]
    )


def test_every_reachable_refusal_is_declared() -> None:
    """The original defect: a refusal the code can raise and the document does not mention."""
    missing = {
        key: sorted(codes - DECLARED.get(key, set()) - set(UNREACHABLE.get(key, {})))
        for key, codes in WALKED.items()
    }
    missing = {key: codes for key, codes in missing.items() if codes}
    assert not missing, (
        "these operations can raise a status the spec does not declare; add a `responses=` "
        f"entry with a description covering every branch that produces it: {missing}"
    )


def _invisible_to_the_walk(key: tuple[str, str]) -> set[str]:
    """Refusals that reach a route through a DEPENDENCY rather than a call, so the walk
    cannot see them however correct they are.

    Exactly two, and the narrowness is the point. `CurrentUser` produces the 401 on all 63
    gated operations and `AdminUser` the 403 on the 20 admin ones, neither of them by a call
    the handler makes. Everything else is walkable, so a `require_role` 403 on a route that
    never calls it, or a 429 on a route behind no throttle, still fails below - and the first
    of those is a mistake this project has actually made, on 12 operations at once.
    """
    return {"401"} | ({"403"} if key[1].startswith(f"{ROOT}/admin/") else set())


def test_nothing_is_declared_that_cannot_be_raised() -> None:
    """The same lie pointing the other way, and the easier one to commit: copying a
    `responses=` block onto a neighbouring route is a one-line edit, and no status-code check
    notices."""
    spurious = {
        key: sorted(codes - WALKED.get(key, set()) - _invisible_to_the_walk(key))
        for key, codes in DECLARED.items()
    }
    spurious = {key: codes for key, codes in spurious.items() if codes}
    assert not spurious, (
        "these operations declare a status nothing in them can raise; either the `responses=` "
        f"is wrong or the handler changed: {spurious}"
    )
