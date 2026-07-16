# isachore

Chore management for households. Keep track of who does what, see what's
overdue, what has to be done today, and what's coming up — shared between
multiple people, with a JSON API so mobile clients can join later.

## Stack

| Layer    | Tech                                                              |
| -------- | ----------------------------------------------------------------- |
| Backend  | FastAPI · async SQLAlchemy 2 · asyncpg · Alembic · Python 3.13 (uv) |
| Frontend | React 19 · TypeScript · Vite · Tailwind CSS v4 · react-router 8 · shadcn/ui (Radix) |
| Database | PostgreSQL 18                                                     |
| Infra    | Docker everywhere (dev and prod)                                  |

## Quickstart (dev)

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.cli create-admin --email you@example.com --name You
```

There is no self-registration: the first admin is created with the command
above (it prompts for a password), and every other user is created by an
admin in the UI under **Admin → Users**.

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

## Frontend UI

The UI is built on [shadcn/ui](https://ui.shadcn.com) (the `radix-nova` style,
Radix UI under the hood). Components you own and can edit live in
`frontend/src/components/ui/`; the config is `frontend/components.json`. Import
them through the `@/` alias (e.g. `@/components/ui/button`) and combine classes
with the `cn()` helper in `frontend/src/lib/utils.ts`.

Add more components with the CLI (run from `frontend/`):

```bash
# NOTE: this prompts to overwrite the brand-customised button.tsx — decline it,
# which the piped "n" does. If it changed package.json, also install in the
# container (a named volume shadows the container's node_modules).
printf 'n\n' | npx shadcn@latest add <component>
docker compose exec frontend npm install
```

- **Design tokens & theming** live only in `frontend/src/index.css`. The teal
  brand is preserved; the light/dark palettes are the `:root` / `.dark` blocks.
- **Dark mode**: `useTheme()` from `frontend/src/theme/`, toggled from the top
  bar. It follows the OS preference until the user picks a side (persisted to
  `localStorage`); the calendar starts weeks on Monday.
- **Toasts**: `import { toast } from 'sonner'` and call `toast.success(...)`
  for success feedback; the single `<Toaster />` is mounted in `main.tsx`.

Libraries the migration added: `radix-ui`, `class-variance-authority`, `clsx`,
`tailwind-merge`, `lucide-react` (icons), `tw-animate-css`, `shadcn` (provides
`shadcn/tailwind.css`), `react-day-picker` + `date-fns` (date picker) and
`sonner` (toasts).

## Tests

Backend uses pytest, frontend uses vitest; both can report coverage. Run the
backend suite inside the container so the `db` host resolves.

```bash
docker compose exec backend uv run pytest                          # backend
cd frontend && npm run test                                        # frontend

# with coverage:
docker compose exec backend uv run pytest --cov=app --cov-report=term-missing --cov-report=html
cd frontend && npm run test:coverage
```

Coverage prints a per-file table in the terminal and writes a browsable HTML
report — open `backend/htmlcov/index.html` or `frontend/coverage/index.html`.
Every feature should ship with tests; both suites must pass before committing.

## TODO

The idea, step by step. Done so far: project scaffold, linters + pre-commit
hook, Docker dev/prod, hello world at `/`, login page UI at `/login`, chores +
users management UI, a shadcn/ui component kit with light/dark theming, and a
self-service profile page (name / password / avatar upload) reached from an
avatar menu in the top bar.

The app is organised into four areas (context for future work):

- **Homepage**: due views for the active user (what is overdue, due today, due soon).
- **Admin**: manage server settings (not yet implemented), users, and anything else that comes up.
- **Chores management**: manage the household's chores.
- **Tags management**: create, edit and delete tags.

- [ ] Tags management (create/edit/delete tags)
- [ ] Household crud
- [ ] Admin: server settings
- [ ] Due views: what is **overdue**, what has to be done **today**, what is due **in a few days**
- [ ] chores changes log (see who changed the chores)
- [ ] Mark chore as done / completion history
- [ ] API keys for mobile / 3rd-party clients (reuse `auth_tokens` via `Authorization: Bearer`)
- [ ] CI (lint + test on push)
- [ ] Prod deploy hardening (TLS, real secrets management, DB backups)

Design mockups live in `../isachore-design/` (login = variant 1a).
