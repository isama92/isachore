# Docker, nginx, CI and the spec pipeline

## Layout

Everything Docker-related lives in `docker/`, except the dev compose file, which stays at the
root as `compose.yml` because it is the everyday entry point.

`docker/` holds `backend.Dockerfile` and `frontend.Dockerfile` (multi-stage), `nginx/` (six
nginx configs: two mode files, three baked snippets and a baked http-context map file), and one
self-contained `compose.prod.<mode>.yml` per prod deployment mode: http / tls / traefik.

**Prod is pull-only.** `compose.yml` is the ONLY file with `build:` blocks; the prod mode files
carry `image:` and nothing else, so a deployment is a compose file, a `.env` and a
`docker compose pull` with no repo checkout on the host. Never add `build:` back to a prod mode
file: on a server there is no `./backend` to build from, so `up -d` would fail confusingly.

Relative paths in a prod mode file (`.env`, `./volumes/db`, `./nginx.tls.conf`) resolve against
**the compose file's own directory**, not the repo root. Running one from the repo therefore
wants a `docker/.env` (already gitignored) and creates `docker/volumes/`; `.gitignore`'s
`volumes/` entry is unanchored so that cannot be committed.

## The boot migration

**`backend/docker-entrypoint.sh` runs `alembic upgrade head` on boot**, so an upgrade is `pull` +
`up -d`. It is baked in as `ENTRYPOINT` in the `dev` and `prod` stages, which is what keeps this
out of the compose files entirely: operators already hold copies of the prod mode files, and
those must stay `image:`-only.

It installs to `/usr/local/bin`, not `/app`, because the dev stage ships no source (only the bind
mount) and a mount there would shadow it.

Two rules when touching it:

- It migrates **only when `$1` is `uvicorn`**, since
  `run --rm --no-deps backend python -m app.cli generate-key` is the documented way out of a
  deploy the startup check rejected and deliberately runs with no database. An unconditional
  upgrade would break exactly that recovery path.
- `set -e` must stay, so a failed migration crash-loops the container instead of serving against
  a schema the code does not match.

`RUN_MIGRATIONS=false` opts out — shell-only, deliberately NOT a `Settings` field: no Python reads
it, and pydantic's `extra="ignore"` makes a stray var in `.env` harmless. Concurrency is a
documented operator constraint, not a lock: two instances booting against one database race on
`alembic_version`.

**Neither suite reaches it, so verify by hand** after touching the script or either `ENTRYPOINT`:

```bash
docker compose down -v && docker compose up -d --build backend
docker compose logs backend | grep entrypoint:
docker compose exec db psql -U isachore -d isachore -c 'SELECT version_num FROM alembic_version'
```

The last must be non-empty. Check both other paths too, which are the ones easy to break:

```bash
docker compose run --rm -e RUN_MIGRATIONS=false backend uvicorn --version   # must log the skip
docker compose stop db
docker compose run --rm --no-deps backend python -m app.cli generate-key    # must still print a key
```

The opt-out only reaches the container through `.env`: the backend block has just `env_file`, so a
bare `RUN_MIGRATIONS=false docker compose up` is silently ignored.

## Build contexts

Build **contexts stay `./backend` and `./frontend`** even though the Dockerfiles moved, because
every `COPY` / `--mount=source=` inside them is context-relative. Only a
`dockerfile: ../docker/<name>.Dockerfile` was added (a relative `dockerfile` resolves from the
context). The `.dockerignore` files stay beside the contexts too, which is where Docker looks for
them.

The frontend prod stage takes its nginx configs from the **`nginxconf` named build context**
(`docker/nginx`), not the build context. Any compose block or `docker build` that targets `prod`
needs `additional_contexts: {nginxconf: ./docker/nginx}` /
`--build-context nginxconf=./docker/nginx`, or `COPY --from=nginxconf` degrades into trying to
pull an image called `nginxconf`. It is declared on the dev block too for exactly that reason.

## nginx

`nginx.tls.conf` is baked to `/etc/nginx/modes/tls.conf`, where it is inert (nginx only
auto-includes `conf.d/*.conf`), *and* bind-mounted by the tls mode from beside the compose file.
The baked copy exists so an operator can extract the version matching their image; if you change
that conf, keep both the Dockerfile path and the compose bind mount in step.

### `nginx-docs.conf`

A second baked snippet, and the only place the deployment relaxes the CSP. It carries the shared
body of the two API-reference locations (`/docs`, rewritten to the backend's `/redoc`, and
`/openapi.json`), and it exists as its own file because it is *location*-context where
`nginx-common.conf` is server-context. Ten things to keep straight:

- **It has to restate every inherited security header**, because nginx replaces an inherited
  `add_header` set rather than merging it — the same rule as `/sw.js`, but here the point is to
  widen the CSP rather than to avoid losing it. **A new security header therefore goes in
  `nginx-headers.conf` and nowhere else**: that third snippet is included at server level from
  `nginx-common.conf` and again at location level from `nginx-docs.conf`, so one edit reaches
  both. It exists because the hand-written second copy this feature shipped with restated five
  where six were inherited and silently dropped HSTS in the tls mode — the one mode that has it.
  Only CSP and HSTS stay out of the shared file, and both for stated reasons.
- **The CSP differs from the app's by exactly one directive**, `worker-src 'self' blob:`, which
  ReDoc needs to build its search index — without it the page renders and the search box is dead.
  There is no third-party origin in it at all: the bundle is vendored into the backend image and
  Google Fonts is off (`api/v1/docs.py`). It stays location-scoped rather than joining the
  app-wide policy because nothing in the SPA makes a blob worker. `'unsafe-inline'` is
  deliberately **absent** from `script-src`, since ReDoc's page carries no inline script — Swagger
  UI's does, which is a second reason only one reader is published.
- **HSTS reaches it through `$hsts`, which is baked, and that is a deployment-safety rule rather
  than a style one.** The map lives in `nginx-maps.conf` -> `conf.d/00-isachore-maps.conf` because
  the tls mode bind-mounts an *operator's own* copy of `nginx.tls.conf` over `conf.d/default.conf`:
  defining the variable in a mode file meant that anybody upgrading with the copy they already had
  got `nginx: [emerg] unknown "hsts" variable` and a container that would not start — the whole
  site, not just the reference. **Nothing the baked snippets reference may be defined in a mode
  file.** The map keys on `$scheme`, so HSTS is sent exactly where nginx itself terminated TLS.
- **The refusal is not shared, so `error_page` sits at the call site** beside `proxy_pass`:
  `/docs` redirects a person to `/login`, `/openapi.json` answers a plain 401 in the API's own
  `ErrorDetail` shape. Giving both the redirect meant a client generator fetching the spec
  followed it to 200 OK of SPA HTML and reported a parse error instead of "sign in".
  `@docs_sign_in` also needs `absolute_redirect off`, or nginx builds the `Location` from its own
  listen scheme and downgrades an HTTPS visitor to plain HTTP in the http and traefik modes, where
  TLS is terminated upstream.
- **It redirects to `/login?next=/docs`, and that value is a LITERAL.** `$request_uri` would be
  the general answer and is the wrong one: it carries the query string, nginx has no urlencode, so
  a `?` or `&` in the path produces a mangled parameter. A literal works because this named
  location is reached from one place — `/docs`'s own `error_page`, since `/openapi.json` answers
  `@docs_unauthorised` instead. The SPA still validates it (`safeReturnPath`), because the
  parameter is client-controlled whatever nginx sends, and it honours it with
  `window.location.assign` rather than react-router: `/docs` is not an SPA route and `App.tsx` has
  no catch-all, so a client-side navigation there renders a blank page. It is `location.replace`,
  not `assign`: nginx's 302 already replaced the /docs entry, so pushing would leave Back on the
  login page with a live session, bouncing forward and stranding what came before.
- `https://cdn.redoc.ly/redoc/logo-mini.svg` stays blocked on purpose, so /docs logs exactly one
  CSP error on every load. Anything else in that console is a real finding.
- **The page lives at the app root (`/redoc`), NOT under `/api/v1`, and that is the gate.** nginx
  gates one exact location and proxies all of `/api/` ungated, so moving the page under the API
  prefix for tidiness would publish the whole reference anonymously. Its bundle goes under
  `/api/v1/docs/` for the mirror-image reason: public JavaScript needing no gate, and no new nginx
  location. Both halves are asserted in `tests/test_docs_page.py`, including the absence of a
  route at `/api/v1/docs/redoc`.
- **ReDoc is vendored, pinned by digest**, by the two `ARG`s at the top of
  `docker/backend.Dockerfile`: a version alone still trusts whatever the CDN serves under that
  tag. It lands in `/opt/redoc`, outside `/app`, because the dev stage's bind mount would hide it —
  the `docker-entrypoint.sh` reasoning again — and `prod` needs its own `COPY --from=builder`,
  since it starts from a bare python image. Bumping means changing both ARGs; a wrong digest fails
  the build rather than shipping.
- The gate is `auth_request` against `GET /api/v1/auth/verify`, a 204-or-401 route that exists for
  nothing else. Its only caller is a conf file, so it reads as dead code from inside Python —
  hence the docstring. The subrequest is a GET, so CSRF exempts it.
- `proxy_pass` is at the call site, not in the snippet, because the two locations differ in
  exactly that. `/redoc` itself is NOT proxied and falls through to the SPA.

## Scheduled jobs

An in-process APScheduler (`app/core/scheduler.py`), started and stopped by the `lifespan` in
`main.py`. Two jobs today: the hourly invitation-expiry sweep and the nightly household-log prune.

Each pairs a `run_*` entry point with a CLI command so an operator can run it once by hand, and
each assumes a single web process, which is what the prod compose files run — behind several, gate
them with a Redis lock.

Neither suite runs a job for real, so a new one needs a by-hand check plus a registration test
asserting the trigger string (see `tests/test_invitation_expiry.py`).

## CI

`.github/workflows/`:

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | `pull_request`, and `workflow_call` from `publish.yml` | ruff + pytest + eslint + prettier + `tsc -b` + vitest, plus a no-push build of both prod images on pull requests ONLY |
| `publish.yml` | push to `main` | calls `ci.yml`, then pushes `ghcr.io/isama92/isachore-{backend,frontend}:latest` |
| `spec.yml` | push to `main` under `paths: backend/**` | regenerates `docs/api/openapi.yaml` and opens a PR |

`ci.yml` deliberately has no `push` trigger, or every `main` commit would run it twice. The image
build is PR-only since on the merge path `publish.yml`'s own build is the gate.

### The two `paths-ignore` lists are deliberately NOT identical

This rule used to say the opposite. Both skip the root prose files. Only `publish.yml` also skips
`docs/**` (a spec change ships no new image).

`ci.yml` must not, because `tests/test_openapi_spec.py` is the only guard on the committed spec and
a spec-only PR would otherwise run nothing at all — merging green and then failing on the *next*
person's backend PR. `docs/architecture/**` is listed separately on `ci.yml` for that reason: the
narrow path keeps prose out of CI without disarming the spec guard.

Do NOT add `**.md` to either, since prettier does check markdown under `frontend/`.

### Two one-time manual steps

Neither is scriptable, and both fail with an error that does not name the setting:

- GHCR packages are created **private** on first publish and inherit nothing from repo visibility,
  so both must be flipped to public (Packages > package > settings) or every `docker compose pull`
  in README.md's Production section fails with `denied`.
- `spec.yml` needs Settings > Actions > General > "Allow GitHub Actions to create and approve pull
  requests".

### Why `spec.yml` opens a PR rather than pushing

`main` is protected (`lock_branch`, one approving review, `enforce_admins: false`) and
`GITHUB_TOKEN` is not an admin, so a direct push is refused outright.

It cannot loop into `publish.yml` for two independent reasons — a `GITHUB_TOKEN` push triggers no
workflow, and `publish.yml` ignores `docs/**` — and it needs no database, because every `Settings`
field has a default and `app.openapi()` reads only the route table. That last fact is what lets the
README document one regeneration command that works from a bare checkout and produces
byte-identical output to CI's (the commands differ only in the temp path).

`redocly bundle` was measured to emit identical YAML from a dumped file and from the live URL, which
is the property the whole job rests on: were it not so, the bot would open a formatting-only PR after
every backend merge.

**A bot PR triggers no CI**, because GitHub raises no workflow events for `GITHUB_TOKEN` actions —
the same rule the anti-loop argument relies on. So `test_openapi_spec.py` does not run on the one PR
that only ever changes the spec. Tolerable today: that diff is output of the very commands the test
compares against, and `main` has no required status checks. Add one and these PRs become unmergeable
without a manual commit.

### The Dockerfiles own the toolchain versions

CI installs python, uv and node on the runner rather than running the suites inside the images, but
it `sed`s the versions out of `docker/*.Dockerfile` instead of restating them, so a base-image bump
reaches CI on its own.

Do not reintroduce a literal pin in `ci.yml`: it used to have them, and a Dependabot bump to
`python:3.14-slim` left CI testing 3.13 while the published image shipped 3.14.
`backend/.python-version` is the one remaining mirror, since uv obeys it and a mismatch means
`uv run` finds no interpreter inside the image; CI asserts it matches.

## The committed OpenAPI spec

`docs/api/openapi.yaml` is committed generated output, regenerated with the pinned
`npx @redocly/cli@2` command in README.md — by hand, or by `spec.yml` after a merge.

`tests/test_openapi_spec.py` is the guard, comparing the committed file to `app.openapi()`. It runs
on a backend change, and (since `docs/**` came off `ci.yml`'s `paths-ignore`) on a spec-only change
too, which is what stopped a hand-edited spec merging green and failing on the next person's PR.

It reaches outside `backend/`, which the dev container cannot normally see, hence the read-only
`./docs:/docs:ro` mount on the backend service in `compose.yml` — a container predating that mount
fails the test with a message saying so.

**At `/docs`, never `/app/docs`**: nested inside the `./backend:/app` bind, Docker has to
materialise the mountpoint, which leaves an untracked root-owned `backend/docs/` in the source tree,
and deleting that empty directory silently breaks the mount in the running container. `_find_spec`
walks parents to `/`, so the depth does not matter to the test.

`pyyaml` is a declared dev dependency for it rather than borrowed from `uvicorn[standard]`, where it
merely happens to be today.

## Smoke-testing prod

No longer builds anything: the mode files pull `:latest` from GHCR, so what you test is the last
merge to `main`, not your working tree. Use a separate project name and a `docker/.env`:

```bash
docker compose -f docker/compose.prod.http.yml -p isachore-prod up -d
docker compose -f docker/compose.prod.http.yml -p isachore-prod down -v
```

To exercise a prod *Dockerfile* change before it is published, build it directly instead of through
compose:

```bash
docker build -f docker/frontend.Dockerfile --target prod \
  --build-context nginxconf=./docker/nginx ./frontend
```

On a PR, `ci.yml`'s `images` job does the same build, so a broken prod Dockerfile fails the PR
rather than the publish.
