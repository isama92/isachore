# Frontend mechanics

The *rules* live in [guidelines.md](../../guidelines.md#frontend-patterns). This file is the
rationale behind the ones that are not obvious, and the mechanics you need when changing them.

## Auth context

`useAuth()` from `src/auth/useAuth.ts`; API calls through the `api` wrapper in `src/lib/api.ts`
(throws `ApiError`). Protected routes wrap in `RequireAuth` / `RequireAdmin`
(`src/components/`); authenticated pages render under the `TopBar`.

### `RequireAuth` renders `<Outlet key={user.id} />`, and that key is load-bearing

Switching identity (impersonation starting or stopping) has to throw the page away, because
*nothing else would*: `refresh()` updates the context and `claimTableSettings` clears the
remembered filters, but no page's load effect depends on the auth context — `useServerTable`'s
fetch deliberately does not, `useFilterOptions` has `[]` deps, and Home and Unscheduled
lazy-initialise `assigneeIds` from `user.id` exactly once. Without it an admin leaving an
impersonated session keeps that person's rows on screen.

The key is `user.id`, NOT the user object: `refresh()` also runs after a profile save, which
must not remount. Both directions are pinned in `RequireAuth.test.tsx`.

What makes the remount actually clean is an ordering in `AuthProvider`: all four adoption paths
call `claimTableSettings(me.id)` *synchronously* immediately before `setUser(me)`
(`AuthProvider.tsx:54,106,137,150`). `useServerTable` reads `localStorage` in a lazy `useState`
initialiser during the mount render, before any effect, so moving that clear into an effect
would hand the remounted page the impersonated user's stored filters for one fetch. Keep it
synchronous and keep it first.

The URL query string is deliberately NOT rewritten, so a filter from the impersonated session
stays in the address bar; every list endpoint scopes through `member_household_ids`, so it
yields an empty page rather than someone else's data.

## Server-driven tables

Every list view is `DataTable` + `useServerTable` (`src/components/data-table/`), TanStack Table
in fully manual mode with the fetching inside the hook. A column's `id`/`accessorKey` IS the
server sort key, so it has to match that endpoint's whitelist (`CHORE_SORT_COLUMNS` and friends)
or sorting breaks silently.

**State lives in the URL**, and with a `storageKey` also in `localStorage` under
`isachore-table-<key>`. There are eight keys; `household-members` is deliberately shared by both
household edit pages.

| Page / component | `storageKey` |
|---|---|
| `pages/Chores.tsx` | `chores` |
| `pages/History.tsx` | `history` |
| `pages/Households.tsx` | `households` |
| `pages/Logs.tsx` | `logs` |
| `pages/Tags.tsx` | `tags` |
| `pages/admin/Households.tsx` | `admin-households` |
| `pages/admin/Users.tsx` | `admin-users` |
| `components/households/HouseholdMembersTable.tsx` | `household-members` |

Storage is read ONCE at mount and what comes back *becomes* that mount's defaults, which is the
whole trick: it buys "URL wins over storage, storage wins over the page's own defaults" with no
extra branch and no mount-time URL rewrite (which would cost a second fetch and a flicker).
`deriveState` and `applyOwnedParams` must keep comparing against that same `defaults`: each
encodes "the default", one as the fallback and one as what to omit from the URL, and they have
to agree or a value equal to it resolves two ways.

**The page number is never stored**, only page size / sort / filters, so every arrival starts at
page 1. A stored page can be out of range after deletions and nothing clamps it.

**`setSearchParams` does not compose within a tick.** react-router hands the updater the current
render's params (its own docs say multiple calls "will not build on the prior value"), so two
`setFilter` calls in one tick both start from the same place and the last silently wins. Change
several filters through `setFilters`.

Each setter's early-return guard is also what keeps `loading` honest, since `mutate` flips it
true and with no URL change there is no request and so no `.finally` to flip it back: a test for
one of those guards must assert `loading`, or it pins nothing.

**Stored settings are untrusted**, validated per field (a bad value falls back on its own, not
all-or-nothing), and a 400/422 response clears that table's key so a stored sort the server no
longer accepts cannot wedge a page forever.

404 does NOT clear, which is why `Tags` prunes a dead `household_id` itself once its household
list loads: `list_tags` 404s for a household you are not in, and its selector is hidden below two
households, so nothing on screen could clear it. `Chores`, `History` and `Logs` prune too (via
latest-value refs, so the options are not refetched), though they merely return an empty page.

Two wrinkles worth copying if a fourth page joins them: History's prune runs on the options
request's **failure** path as well, because its hidden-bar branch reads no payload and a helper
would otherwise keep filters applied with no Select on screen to clear them; and `Logs` prunes its
`action` filter with no network at all, in the same `setFilters` call, since that option list is a
closed const of ours rather than something a request can teach us.

`clearTableSettings()` runs on logout because the saved filters name colleagues and households;
theme and language deliberately survive, being the browser's preferences rather than one account's
data.

## A Radix Checkbox inside a form swallows Enter

Deliberately — WAI-ARIA says Space toggles a checkbox — which is stricter than the native
`<input type="checkbox">` it stands in for, where Enter submits.

`Login.tsx` hands the key back, and if a second form ever needs the same thing, copy all four
clauses rather than the first one:

1. `preventDefault()` runs first, because Radix's `composeEventHandlers` runs the consumer's
   handler before its own and skips its own once the default is prevented. That single call both
   frees the key and keeps Enter from toggling the box.
2. Then `requestSubmit()`, never the submit handler directly, so constraint validation still runs.
3. `requestSubmit()` consults no button, so unlike implicit submission it is NOT stopped by a
   disabled submit button.
4. Without `e.repeat` and the submitting flag, a held Enter auto-repeats a burst of requests.

Three other forms have the same shape and are deliberately untouched (`ChoreForm`,
`admin/ServerSettings`, `users/UserForm` — the last is the one where the checkbox is the final
control before submit). Extract a `lib/` helper if a second one adopts it; one caller does not
earn the indirection.

## UI components

shadcn/ui (radix-nova) live in `frontend/src/components/ui/`, config in `components.json`. Import
via the `@/` alias and compose classes with `cn()` (`@/lib/utils`).

Several primitives are brand customised (Button, Input/Textarea, Select trigger, Label + Table
headers, Monday-first Calendar): keep using them rather than raw HTML, and when one needs brand
radius/sizing, edit the component itself rather than fighting it with per-call classes.

The shadcn radius scale (`--radius-sm/md/lg/...`) is deliberately NOT redefined in `index.css`;
brand roundness comes from `rounded-input` (13px) / `rounded-button` (15px). tailwind-merge does
not dedupe those custom radius tokens against a base `rounded-*`, so set radius (and height) in
the component's own class string (as Button/Input/Select do), not via a call-site `className`.

Adding a component re-pulls its registry deps and offers to overwrite files it thinks it owns,
`button.tsx` and `chart.tsx` among them: always decline
(`printf 'n\n' | npx shadcn@latest add <name>`), then double-install if `package.json` changed
(host + `docker compose exec frontend npm install`).

The radix-nova style ships `@import 'shadcn/tailwind.css'` (the `shadcn` package supplies the
`data-open`/`data-checked`/... variants, resolved through its `exports` map to
`dist/tailwind.css`), plus the unified `radix-ui` package and `tw-animate-css`: don't remove them.

### `chart.tsx` is modified too, and not cosmetically

It does not belong on the brand-customised list and needs its own note. Two local extensions,
neither upstream:

- `ChartStyle`'s `safeId` / `CSS_IDENT` / `SAFE_COLOR` are the sanitiser around its
  `dangerouslySetInnerHTML` — the reason the CSP keeps `style-src 'unsafe-inline'`.
- `ChartTooltipContent`'s opt-in `hideZero` drops zero-valued series from the rows, which a
  stacked chart needs because recharts sends one payload entry per series whatever the value.

Losing the first is a security regression, so treat re-pulling this file as the higher-risk case,
not the lower one. Both are pinned by `ui/chart.test.tsx`, and `hideZero` also fails `tsc` through
its `Statistics.tsx` call site, so a stock overwrite cannot reach `main` — but it lands as a CI
failure whose cause is several steps from the command that caused it. Reflexively hitting `y`
here costs an afternoon.

## Theme

`ThemeProvider` + `useTheme()` in `frontend/src/theme/` (context/provider/hook split, same rule as
`src/auth/`). Light mode is the teal brand; dark is derived.

The picker is the Profile page's **Appearance** section (Catppuccin flavour + accent, saved
optimistically with rollback, like language), NOT `TopBar`.

Toasts: `toast.success(...)` from `sonner`, a single `<Toaster />` in `main.tsx`. Feedback
pattern: success -> toast, errors -> inline text.

### Inline errors on a list page need help

"Inline" there means a banner above the filter bar, and a row action failing on row 90 of 100
reports itself entirely off-screen. The answer is not a toast, which forks the convention and
would leave two actions on one page behaving differently; it is to make the banner reach the
user: `role="alert"` on the paragraph, plus `scrollIntoView({ block: 'nearest' })` in an effect
keyed on the error (a no-op when it is already visible, and setState-free so it is exempt from
the no-setState-in-effect rule).

`Chores.tsx` does this, because clone is the one row action that can fail on the way *out* rather
than from inside a confirmation dialog the user is already looking at. The same banner sits on
`Tags`, `Households`, `History`, `Home`, `Unscheduled` and both admin tables, all with row
actions that can fail, and none of them do this yet — lift the ref-plus-effect if you touch one,
or sweep the lot into a shared component.

A form's inline error needs none of this: it sits beside the button that was just pressed.

## Design tokens and brand artwork

Colours, fonts, radii and shadows live ONLY in `frontend/src/index.css`; never hardcode hex in
components. They are split by role: theme-invariant tokens (fonts, shadows, brand radii) under
`@theme`; the runtime colour vars under `:root` / `.dark`; the utility mappings (shadcn's
`--color-*` names and the legacy isachore aliases) under `@theme inline`. Tailwind v4 is
CSS-first: there is NO `tailwind.config.js` and none should be added.

The logo is a traced whiteboard drawing of a cat, in `frontend/src/components/brand/` as
`BrandMark` (the head knocked out of a `bg-primary` tile) and `BrandCaption` (the handwritten "Do
task!"). The mark is in the sidebar header and on Login; the caption is on Login ONLY, because at
the width the sidebar header allows it shrinks to an illegible smudge (it is nearly 2:1, so always
size it by width).

The path data in `paths.ts` and in `public/favicon.svg` is machine-traced from a photo of the
drawing, and the two carry the same artwork under the same `MARK_VIEWBOX`: never hand-edit either,
and if the artwork is ever re-traced, replace both together or the tab icon stops matching the
app. The tracing pipeline is not kept anywhere; treat the committed paths as the artwork.

The favicon is the only place the teal is hardcoded, carrying its own `prefers-color-scheme` block
because a browser tab cannot read the app theme; everything in-app goes through `--primary` and so
tracks the user's accent.

The sidebar's brand `<Link>` needs its own `aria-label`: in icon mode the wordmark is
`display:none`, which also drops it from the accessibility tree.

## i18n

`react-i18next` + `i18next`. `frontend/src/i18n/` mirrors `theme/`: `languages.ts` (the closed
`Language` set `'en' | 'it'`, `LANGUAGES` autonyms, `DEFAULT_LANGUAGE` = `en`, `isLanguage` guard,
`localeFor` -> BCP47), `i18n.ts` (singleton init, the typed-keys `declare module` augmentation, the
`changeLanguage` persist wrapper, the `languageChanged` -> `<html lang>` listener),
`useLanguage.ts`, and `locales/{en,it}.json`. Initialised by `import './i18n/i18n'` in `main.tsx`,
no React provider.

Keys are typed off `en.json`, so a typo or a key missing from `en.json` fails `tsc -b`; there is no
check that `it.json` matches, so keep it in lockstep manually. Keys are grouped by feature,
dot-separated. Interpolation is `{{var}}`; a conditional becomes two keys; dynamic keys use a
literal-union template.

**Persistence mirrors theme's "persist only on an explicit choice":** the `changeLanguage()`
wrapper in `i18n.ts` writes `localStorage` (`isachore-language`); the `languageChanged` listener
only sets `<html lang>` and must NOT persist. Use the wrapper (via `useLanguage.setLanguage`, or in
`AuthProvider`); call bare `i18n.changeLanguage` only for a non-persisting reset (test teardown).

Per-user `users.language` (nullable; `Language` Literal in `schemas/user.py`, kept in sync with the
frontend type) is in `UserRead` + `ProfileUpdate` — self-service, NOT admin `UserUpdate`, like theme
— and adopted by `AuthProvider.syncAppearance` (skipped while impersonating). Saved optimistically
on Profile then PATCHed with rollback. Dates: `formatDate` in `lib/chores.ts` uses
`localeFor(i18n.language)`.

Not translated, deliberately: the brand name `isachore`, the Catppuccin flavour names, the 14 accent
colour names, and the handwritten `BrandCaption` ("Do task!") since it is artwork rather than a
string.

**Gotcha:** a handler closure captures the render-time `t`, so a toast fired right after switching
language would show the OLD language. The Profile language-save success toast reads via the `i18n`
singleton (`i18n.t(...)`) so it confirms in the just-selected language; rollback/error paths keep
the closure `t`.

## Readable 422s

`lib/validationError.ts` turns pydantic's `detail` *list* into one sentence, and `handle()` in
`api.ts` calls it whenever `detail` is not a string. Every hand-raised `HTTPException` carries a
string and is shown verbatim; only pydantic sends the list, which used to fall through to
`res.statusText` ("Unprocessable Content").

It keys off the stable `type` discriminator rather than the English `msg`, through closed `const`
tuples (`VALIDATION_TYPES`, `FIELD_NAMES`) so the dynamic `errors.validation.*` / `errors.fields.*`
keys typecheck.

Three things not to undo:

- `value_error` is deliberately absent from `VALIDATION_TYPES`, because our own validators write
  better English than any generic (it is unwrapped instead, and `EmailStr` is the one special
  case).
- `ctx` is passed under i18next's `replace` so a pydantic context key can never land as an i18next
  option (`count` would silently switch on pluralisation).
- The wire shape stays the *array*, since `/api/v1` has future non-browser clients. Do NOT add a
  backend `RequestValidationError` handler that flattens `detail` to a string.

Translation goes through the `i18n` singleton, not a captured `t`: `api.ts` has no React context.

## PWA

Installable to a phone home screen. `public/manifest.webmanifest`, `public/sw.js` and the four PNG
icons; `src/pwa.ts` does the registration, called from `main.tsx`.

Like `theme-init.js`, the two `public/` files are outside eslint/tsc (`eslint.config.js` only
matches `**/*.{ts,tsx}`), so `src/pwaManifest.test.ts` is what guards them. Five things not to undo:

- **Registration is `import.meta.env.PROD`-only.** A worker in dev intercepts the requests Vite's
  HMR needs and you get stale modules with no clue why. It also registers immediately when
  `document.readyState === 'complete'` rather than only on `load`: `main.tsx` is a deferred module,
  so `load` may already have fired, and waiting for it would mean never registering.
- **`sw.js` must never cache `/api/`** (nor anything non-GET), **nor `/docs`.** The first: those
  responses are authenticated household data and the app has no offline write model, so caching
  them would put personal data on the device for nothing, and it also means logging out leaves
  nothing behind. The second is a different failure — the prod nginx answers `/docs` from the
  backend (ReDoc), and it is a same-origin `text/html` navigation, so the navigate branch would
  store the API reference as the *offline app shell* and every later offline navigation would
  render the docs instead of isachore. `NOT_THE_APP` is that guard. It lists the HTML one only:
  `/openapi.json` is proxied beside it but ReDoc fetches it with `fetch()` (mode `cors`), which
  reaches no branch at all, so listing it would pin a fall-through rather than a guard.

  Bump `CACHE` when editing the worker, but note that does not prune anything on an ordinary
  deploy: the worker is byte-identical across them, so none activates and each deploy's hashed
  `/assets/` accumulate, which is left to the browser's storage eviction.

  `src/serviceWorker.test.ts` runs the worker in a `node:vm` sandbox against a fake `self` rather
  than grepping its source, so these rules are enforced; only a 200, non-redirected, `text/html`
  navigation may become the shell (a 502 from the proxy mid-deploy resolves normally and would
  otherwise be pinned as the offline shell). When adding a rule there, **delete it and check the
  test actually fails**: a request shape matching no branch (say a `no-cors` `/api/` GET) falls
  through whether or not the guard exists.
- **The maskable icon needs MORE padding than the favicon, not less.** Android crops it to the
  launcher's shape and only guarantees the inner ~80%, so it is a full-bleed teal square with the
  head at ~75% width, while the `any` icons keep the tight rounded-tile crop. iOS ignores manifest
  icons entirely and uses `apple-touch-icon.png`, which must be opaque (transparency renders black)
  and square (iOS applies its own squircle).
- **nginx (`nginx-common.conf`) uses `expires -1` for `/sw.js`, not `add_header Cache-Control`**:
  nginx *replaces* inherited `add_header` directives instead of merging, so an `add_header` there
  silently drops the CSP and the four other security headers from that response. For the same
  reason the manifest's type comes from `default_type` in its own `location`, not a `types` block,
  which would replace the whole inherited MIME map. Without it the manifest is
  `application/octet-stream`, and `nosniff` then makes the browser reject it and the app is not
  installable.
- **HTTPS is required**, so this only works in the tls/traefik modes or behind a TLS-terminating
  proxy. No CSP change was needed: `worker-src` and `manifest-src` both fall back to
  `default-src 'self'`.

## Testing the frontend

`cd frontend && npm run test` (coverage -> `frontend/coverage/`). Use `renderWithProviders` + the
`fetch` mock from `src/test/utils.tsx` and the synthetic fixtures in `src/test/fixtures.ts`, never
real personal data. `npm run build` (`tsc -b`) also typechecks tests via `tsconfig.vitest.json`, so
a test type error breaks the build.

**Testing Radix in jsdom:** build the user with `userEvent.setup({ pointerEventsCheck: 0 })` (Radix
sets `pointer-events:none` on the body when a modal opens) and query portaled content with
`within(await screen.findByRole('dialog' | 'alertdialog'))` / `findByRole('option')`. The required
jsdom stubs (`hasPointerCapture`, `scrollIntoView`, `ResizeObserver`, `matchMedia`) are in
`src/test/setup.ts`; don't remove them. `renderWithProviders` wraps `ThemeProvider`, and its
`afterEach` clears `localStorage` + the `.dark` class so theme state can't leak.

**Contenteditable is the one thing jsdom cannot drive**, which is why `src/test/richTextEditorMock.tsx`
exists and is the **only** `vi.mock` in the repo. Page tests about a *form* swap the editor for a
textarea with the same contract (same accessible name via `labelledBy`, value in, string out), which
keeps `getByLabelText('Description')` and `toHaveValue(...)` working.

The real editor is covered in `RichTextEditor.test.tsx`, which works around jsdom by driving commands
instead of keys; it needs `Range.prototype.getClientRects`, `getBoundingClientRect` and
`document.elementFromPoint` stubbed in `test/setup.ts` (ProseMirror hit-tests a click through the last
one and jsdom throws), and it focuses the editable rather than clicking into it.

The toolbar's `useEditorState` took three attempts to pin, because the obvious tests all pass without
it: Tiptap v3's React binding is non-reactive, so `editor.isActive()` read from render is stale, but
the staleness is invisible whenever the **document** changes, since `onUpdate` makes the caller
re-render and recompute the stale read by accident. Asserting `aria-pressed` after an edit proves
nothing; toggling a mark at a collapsed caret fires `onUpdate` too. Only a pure selection move is
document-free, and jsdom refuses arrow keys outright ("Not implemented. The result of this
interaction is unreliable."), so the test drives `setTextSelection` through a harness that owns the
editor.
