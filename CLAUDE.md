# isachore

Chore management app for households: chores shared between multiple people,
overdue / due-today / due-soon views, JSON API for future mobile clients.
Work happens in small steps — check the TODO list in README.md for what's
next, and tick items off there when they're done.

## Stack

- **Backend** (`backend/`): FastAPI, async SQLAlchemy 2 + asyncpg, Alembic,
  pydantic-settings. Python 3.13, managed with uv.
- **Frontend** (`frontend/`): React 19 + TypeScript, Vite, Tailwind CSS v4,
  react-router 8, npm.
- **DB**: PostgreSQL 18. **Docker** for dev and prod (multi-stage Dockerfiles,
  `docker-compose.yml` dev / `docker-compose.prod.yml` prod).

## Commands

```bash
docker compose up --build                          # dev stack: db + backend (reload) + frontend (HMR)
docker compose -f docker-compose.prod.yml up --build  # prod: nginx on :80 serving SPA + /api proxy

docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head   # run alembic INSIDE the container so host "db" resolves

cd backend && uv run ruff check . && uv run ruff format .
cd frontend && npm run lint && npm run format && npm run build   # build also typechecks (tsc -b)

pre-commit run --all-files                         # what the git hook runs
```

## Conventions

- API lives under `/api/v1`, JSON only. Routers in `backend/app/api/v1/`,
  registered in `router.py`.
- Config via `app/core/config.py` (pydantic-settings, env vars from `.env`).
  In compose the DB host is `db`; the code default targets `localhost` for
  host-side tooling. `DATABASE_URL` must use the `postgresql+asyncpg://` scheme.
- No DB models yet. When they arrive: inherit from `app.db.base.Base`
  (has a naming convention for Alembic autogenerate), import them in
  `alembic/env.py`'s metadata scope, migrations via autogenerate.
- Design tokens (colours, fonts, radii, shadows) live ONLY in
  `frontend/src/index.css` under `@theme` — never hardcode hex values in
  components. Tailwind v4 is CSS-first: there is NO tailwind.config.js and
  none should be added.
- Import routing from `react-router` (v8) — never `react-router-dom`.
- Pages in `frontend/src/pages/`, one component per route.
- UI mockups: `../isachore-design/Choreo Screens.dc.html` (login = 1a).

## Gotchas

- After changing `frontend/package.json`: run `npm install` locally (pre-commit
  hooks use local node_modules) AND `docker compose exec frontend npm install`
  (a named volume shadows the container's node_modules).
- Changing `POSTGRES_*` in `.env` after first boot needs `docker compose down -v`.
- Keep the ruff version in `.pre-commit-config.yaml` (`ruff-pre-commit` rev) in
  sync with the ruff dev dependency in `backend/pyproject.toml`.
- Never commit `.env`; dev-only placeholder credentials belong in `.env.example`.
  No real secrets, credentials, or production hostnames anywhere in the repo.
