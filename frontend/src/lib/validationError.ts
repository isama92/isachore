import i18n from '../i18n/i18n'

/**
 * Turns FastAPI's 422 body into one readable sentence.
 *
 * Every hand-raised error in the backend is `HTTPException(detail="<string>")`, which the
 * api wrapper can show as-is. Pydantic is the exception: a `RequestValidationError` sends
 * `detail` as a *list* of `{loc, msg, type, ctx}` objects, so before this existed the
 * wrapper fell through to `res.statusText` and the user was shown the browser's raw
 * "Unprocessable Content".
 *
 * The wire shape stays the machine-readable array - `/api/v1` is a JSON API with future
 * non-browser clients, and flattening it server-side would take that away from them. The
 * translation happens here instead, keyed off pydantic's stable `type` discriminator
 * rather than its English `msg`, which is phrased for developers.
 */

// Pydantic error types we have our own wording for, mapped to the `ctx` key their sentence
// interpolates (null when it takes no value). Deliberately a closed set: the template
// literal below is what makes `t()` typecheck, so a type not listed here falls through to
// pydantic's own `msg` rather than producing a missing-key string.
//
// `plural: true` marks a bound the sentence has to agree with grammatically - "at least 1
// characters" is reachable, since `min_length=1` sits on a chore title, both name fields,
// tag and household names and the 2FA code.
//
// `value_error` is deliberately ABSENT. It is what a custom validator raises, and our two
// (schemas/chore.py, schemas/user.py) write better English than any generic could - see
// messageFor below, which unwraps them.
const VALIDATION_TYPES = {
  missing: null,
  string_type: null,
  string_pattern_mismatch: null,
  int_type: null,
  int_parsing: null,
  bool_type: null,
  bool_parsing: null,
  date_type: null,
  date_parsing: null,
  date_from_datetime_parsing: null,
  datetime_parsing: null,
  list_type: null,
  json_invalid: null,
  string_too_short: { ctxKey: 'min_length', plural: true },
  string_too_long: { ctxKey: 'max_length', plural: true },
  too_short: { ctxKey: 'min_length', plural: true },
  too_long: { ctxKey: 'max_length', plural: true },
  greater_than: { ctxKey: 'gt', plural: false },
  greater_than_equal: { ctxKey: 'ge', plural: false },
  less_than: { ctxKey: 'lt', plural: false },
  less_than_equal: { ctxKey: 'le', plural: false },
  literal_error: { ctxKey: 'expected', plural: false },
  enum: { ctxKey: 'expected', plural: false },
} as const satisfies Record<string, null | { ctxKey: string; plural: boolean }>

type ValidationType = keyof typeof VALIDATION_TYPES

function isValidationType(value: string): value is ValidationType {
  // hasOwn, not `in`: `in` walks the prototype chain, so a type called `constructor` or
  // `toString` would pass the guard and then index to a function. Today that would still
  // come out right, because the resulting spec has no `ctxKey` and mappedMessage's missing
  // bound check sends it to the `msg` fallback - which is why no test can tell the two
  // apart. hasOwn is simply the predicate that means what this asks, rather than one that
  // relies on that coincidence holding.
  return Object.hasOwn(VALIDATION_TYPES, value)
}

// Wire field names we can name in the user's language. The wording was *taken* from the
// label on the form each field belongs to, so "Repeat every" rather than "Interval" - but
// these are independent strings, and nothing keeps them in step if a form label is later
// reworded. That is the deliberate trade: `$t(choreCreate.titleLabel)`-style nesting would
// couple them, at the cost of a reference that breaks silently (i18next renders the literal
// `$t(...)` on a miss) and of picking one referent for names like `title` and `name` that
// several forms share. Re-check this list when renaming a form label. Anything absent falls
// back to the raw wire name; see labelFor.
const FIELD_NAMES = [
  'email',
  'password',
  'current_password',
  'new_password',
  'first_name',
  'last_name',
  'title',
  'description',
  'start_date',
  'repeats',
  'assignment_type',
  'turn_length',
  'repeat_interval',
  'weekdays',
  'name',
  'color',
  'code',
  'role',
  'status',
  'language',
  'theme',
  'accent_color',
] as const

type FieldName = (typeof FIELD_NAMES)[number]

function isFieldName(value: string): value is FieldName {
  return (FIELD_NAMES as readonly string[]).includes(value)
}

// `loc` names the request part first, which tells the user nothing.
const LOCATIONS = new Set(['body', 'query', 'path', 'header', 'cookie'])

// Prefix pydantic puts on anything a custom validator raised.
const VALUE_ERROR_PREFIX = 'Value error, '
// EmailStr also reports `value_error`, but with a message written for whoever wrote the
// regex ("value is not a valid email address: The part after the @-sign is not valid..."),
// so it is the one value_error we answer ourselves rather than passing through.
const EMAIL_ERROR_PREFIX = 'value is not a valid email address'

type ValidationIssue = {
  loc?: unknown
  msg?: unknown
  type?: unknown
  ctx?: unknown
}

/** The field an issue is about: the last named segment of `loc`, or null for a
 *  whole-request error. Skips numeric segments, so `["body", "weekdays", 0]` is about
 *  `weekdays` rather than about item 0. */
function fieldOf(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null
  for (let i = loc.length - 1; i >= 0; i -= 1) {
    const part: unknown = loc[i]
    if (typeof part !== 'string' || LOCATIONS.has(part)) continue
    return part
  }
  return null
}

function labelFor(field: string): string {
  if (isFieldName(field)) return i18n.t(`errors.fields.${field}`)
  // A query parameter, or a field added since this list was written. Opening the
  // underscores up beats both showing the raw snake_case and saying nothing at all.
  return field.replace(/_/g, ' ')
}

/** Pydantic's `ctx` holds the bound that was breached (`max_length`, `ge`, `expected`, ...).
 *  Only primitives, and passed to i18next under `replace` so a context key never collides
 *  with one of its own options (`count` would silently switch on pluralisation). */
function interpolationFor(ctx: unknown): Record<string, string | number> {
  if (!ctx || typeof ctx !== 'object') return {}
  const values: Record<string, string | number> = {}
  for (const [key, value] of Object.entries(ctx)) {
    if (typeof value === 'string' || typeof value === 'number') values[key] = value
  }
  return values
}

/** Our own wording for a mapped type, or null when `ctx` did not carry the value the
 *  sentence needs - in which case the caller falls back to pydantic's `msg`, since an
 *  unresolved `{{max_length}}` (or, for a pluralised key, the bare key) is worse than
 *  developer English. Pydantic always sends `ctx` for a constrained type, so this only
 *  fires on a body that did not come from pydantic. */
function mappedMessage(type: ValidationType, ctx: unknown): string | null {
  const spec = VALIDATION_TYPES[type]
  if (spec === null) return i18n.t(`errors.validation.${type}`)

  const values = interpolationFor(ctx)
  const bound = values[spec.ctxKey]
  if (bound === undefined) return null
  if (!spec.plural) return i18n.t(`errors.validation.${type}`, { replace: values })
  if (typeof bound !== 'number') return null
  // `count` selects the plural form and nothing else: the sentence still interpolates out
  // of `replace`, so it stays true that no pydantic ctx key can reach i18next as an option
  // of its own (a raw `count` in ctx would otherwise switch on pluralisation by accident).
  return i18n.t(`errors.validation.${type}`, { count: bound, replace: values })
}

function messageFor(issue: ValidationIssue): string {
  const type = typeof issue.type === 'string' ? issue.type : ''
  const msg = typeof issue.msg === 'string' ? issue.msg.trim() : ''

  if (isValidationType(type)) {
    const mapped = mappedMessage(type, issue.ctx)
    if (mapped !== null) return mapped
  }
  if (type === 'value_error') {
    if (msg.startsWith(EMAIL_ERROR_PREFIX)) return i18n.t('errors.validation.email')
    if (msg.startsWith(VALUE_ERROR_PREFIX)) return msg.slice(VALUE_ERROR_PREFIX.length)
  }
  // Untranslated, but pydantic's own English beats "Unprocessable Content" and it is the
  // only thing left that describes the actual problem.
  return msg || i18n.t('errors.validation.fallback')
}

/**
 * `null` when `detail` is not a pydantic issue list, which is the signal for the caller to
 * keep whatever message it already had. Several issues are joined; duplicates (the same
 * complaint about two items of one list) collapse.
 */
export function formatValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null

  const messages = new Set<string>()
  for (const entry of detail as unknown[]) {
    if (!entry || typeof entry !== 'object') continue
    const issue = entry as ValidationIssue
    const message = messageFor(issue)
    if (!message) continue
    const field = fieldOf(issue.loc)
    messages.add(
      field ? i18n.t('errors.validation.field', { field: labelFor(field), message }) : message,
    )
  }
  return messages.size > 0 ? [...messages].join('; ') : null
}
