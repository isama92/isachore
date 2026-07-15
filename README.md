# isachore

Chore management for households. Keep track of who does what, see what's
overdue, what has to be done today, and what's coming up — shared between
multiple people, with a JSON API so mobile clients can join later.

## Stack

| Layer    | Tech                                                              |
| -------- | ----------------------------------------------------------------- |
| Backend  | FastAPI · async SQLAlchemy 2 · asyncpg · Alembic · Python 3.13 (uv) |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS v4 · react-router 8   |
| Database | PostgreSQL 18                                                     |
| Infra    | Docker everywhere (dev and prod)                                  |

## Quickstart (dev)

```bash
cp .env.example .env
docker compose up --build
```

| Service       | URL                                     |
| ------------- | --------------------------------------- |
| Frontend      | http://localhost:5173                   |
| Backend API   | http://localhost:8000/api/v1            |
| API docs      | http://localhost:8000/docs              |
| Health check  | http://localhost:5173/api/v1/health     |
| Postgres      | localhost:5432                          |

Production build (serves everything on port 80 via nginx):

```bash
docker compose -f compose.prod.yml up --build
```

One-time setup for the lint git hook:

```bash
uv tool install pre-commit
pre-commit install
```

## TODO

The idea, step by step. Done so far: project scaffold, linters + pre-commit
hook, Docker dev/prod, hello world at `/`, login page UI at `/login`.

- [ ] Household / user / chore models + first Alembic migration
- [ ] Auth backend (register, login, tokens for mobile clients) + wire up the login page
- [ ] Chores table page — list all chores of the household
- [ ] Chore creation page — add a chore (assignees, rotation, tags, period, start date)
- [ ] Due views: what is **overdue**, what has to be done **today**, what is due **in a few days**
- [ ] Mark chore as done / completion history
- [ ] API conventions for mobile clients (token auth, versioning, pagination)
- [ ] Tests: pytest (backend) + vitest (frontend)
- [ ] CI (lint + test on push)
- [ ] Prod deploy hardening (TLS, real secrets management, DB backups)

Design mockups live in `../isachore-design/` (login = variant 1a).
