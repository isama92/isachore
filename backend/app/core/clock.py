"""The current instant, behind a seam.

Everything that asks "what time is it" goes through `now()` so a test can pin the clock.
That matters more than it looks: every due decision in the app is a *day* comparison in some
household's timezone, so the interesting behaviour lives at day boundaries - a chore that
reads as due today at 01:30 in Amsterdam and as due tomorrow half an hour earlier. There is
no way to exercise that from the outside without controlling the clock.

Call it as `clock.now()`, keeping the module qualifier. `from app.core.clock import now`
binds the function object into the importing module's namespace, and monkeypatching this
one afterwards would not reach it.

The pure helpers in `core/chores.py` take `now` as a parameter instead and need none of this;
this exists for the endpoints, which have nowhere else to get it from.

Adoption is deliberately incremental rather than a blanket ban on `datetime.now(UTC)`. Anything
whose *value* a test might need to control goes through here - the four day-boundary reads, and
the soft-delete stamps, which are the timestamps a test asserts on. Token TTLs, audit rows and
invitation expiries still call `datetime.now(UTC)` directly: no test pins them, and routing them
through a seam would suggest they are part of one clock story when they are not. If you find
yourself wanting to freeze one of those, move it here rather than reaching for freezegun.
"""

from datetime import UTC, datetime


def now() -> datetime:
    """The current instant, UTC-aware."""
    return datetime.now(UTC)
