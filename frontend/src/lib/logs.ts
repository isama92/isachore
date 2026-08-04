import type { TFunction } from 'i18next'
import { LOG_ACTIONS, LOG_FIELDS, type LogAction, type LogField } from './types'

/** Whether a wire value is an action this release knows how to name. */
export function isLogAction(value: string): value is LogAction {
  return (LOG_ACTIONS as readonly string[]).includes(value)
}

function isLogField(value: string): value is LogField {
  return (LOG_FIELDS as readonly string[]).includes(value)
}

// Both take `t` rather than reading the i18n singleton, unlike validationError.ts (which has
// to, since api.ts holds no React context): these render inside a component, so they must use
// the render-time translator and follow a language change.

/**
 * The action, named in the user's language.
 *
 * An action this release does not know degrades to a readable form of the raw value, which
 * beats i18next echoing `logs.actions.<whatever>` at somebody. Reachable in one direction
 * only - a newer server writing an action an older client is reading - which is exactly the
 * direction a service-worker-cached shell makes possible.
 */
export function logActionLabel(t: TFunction, action: string): string {
  return isLogAction(action) ? t(`logs.actions.${action}`) : action.replace(/_/g, ' ')
}

/** One moved field's name. Same fallback and the same reasoning as `labelFor` in
 *  validationError.ts: opening the underscores up beats both raw snake_case and silence. */
export function logFieldLabel(t: TFunction, field: string): string {
  return isLogField(field) ? t(`logs.fields.${field}`) : field.replace(/_/g, ' ')
}
