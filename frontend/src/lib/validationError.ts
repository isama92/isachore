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

// Pydantic error types we have our own wording for. Deliberately a closed tuple: the
// template literal below is what makes `t()` typecheck, so a type not listed here falls
// through to pydantic's own `msg` rather than producing a missing-key string.
//
// `value_error` is deliberately ABSENT. It is what a custom validator raises, and our two
// (schemas/chore.py, schemas/user.py) write better English than any generic could - see
// messageFor below, which unwraps them.
const VALIDATION_TYPES = [
  'missing',
  'string_type',
  'string_too_short',
  'string_too_long',
  'string_pattern_mismatch',
  'greater_than',
  'greater_than_equal',
  'less_than',
  'less_than_equal',
  'int_type',
  'int_parsing',
  'bool_type',
  'bool_parsing',
  'date_type',
  'date_parsing',
  'date_from_datetime_parsing',
  'datetime_parsing',
  'list_type',
  'too_short',
  'too_long',
  'literal_error',
  'enum',
  'json_invalid',
] as const

type ValidationType = (typeof VALIDATION_TYPES)[number]

function isValidationType(value: string): value is ValidationType {
  return (VALIDATION_TYPES as readonly string[]).includes(value)
}

// Wire field names we can name in the user's language, wording matched to the label on the
// form the field belongs to (so "Repeat every", not "Interval"). Anything absent falls back
// to the raw name; see labelFor.
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

function messageFor(issue: ValidationIssue): string {
  const type = typeof issue.type === 'string' ? issue.type : ''
  const msg = typeof issue.msg === 'string' ? issue.msg.trim() : ''

  if (isValidationType(type)) {
    return i18n.t(`errors.validation.${type}`, { replace: interpolationFor(issue.ctx) })
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
