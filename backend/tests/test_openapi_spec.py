"""The committed API reference has to still describe the app.

`docs/api/openapi.yaml` is generated output kept under version control, and nothing else
would notice it going stale: `docs/**` sits in both workflows' `paths-ignore`, so editing
the spec runs no CI, and a backend change runs CI that passes whether or not anybody
regenerated the file. So the guard has to live here, on the backend side, where a route
change does run it.

Failing this means the spec is behind the code, not that the code is wrong. Regenerate it
(the command is in README.md's "API documentation" section) and commit the result.
"""

from pathlib import Path

import yaml

from app.main import app

RELATIVE = Path("docs") / "api" / "openapi.yaml"


def _find_spec() -> Path | None:
    """Walk up looking for the spec, because it sits at a different depth in the two places
    the suite runs: CI runs on the runner from a full checkout, where docs/ is a sibling of
    backend/ and so two levels above tests/, while the dev container mounts it at /docs, the
    filesystem root, deliberately outside the ./backend bind (see compose.yml). Nearest match
    wins, so a checkout always finds its own copy first."""
    for parent in Path(__file__).resolve().parents:
        if (parent / RELATIVE).exists():
            return parent / RELATIVE
    return None


def test_the_committed_spec_matches_the_live_schema() -> None:
    spec = _find_spec()
    assert spec is not None, (
        f"no {RELATIVE} above {__file__}. Inside the dev container it arrives as a bind "
        "mount added to compose.yml; recreate the container (docker compose up -d) if "
        "this container predates it."
    )

    committed = yaml.safe_load(spec.read_text())

    # Compared whole rather than path by path: a response, a schema or an enum value going
    # stale is exactly the drift this exists to catch, and those live outside `paths`.
    assert committed == app.openapi(), (
        "docs/api/openapi.yaml no longer matches the app; regenerate it (see README.md)"
    )
