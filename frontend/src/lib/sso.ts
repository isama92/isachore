/**
 * The `?sso_error=` codes the SSO callback can send the login page back with.
 *
 * The backend answers a failed sign-on with a redirect rather than JSON, because the
 * caller is a browser mid-navigation and not the `api` wrapper, so the reason arrives in
 * the query string. This turns it into a translation key.
 *
 * A closed `const` tuple for the same reason `VALIDATION_TYPES` is one in
 * validationError.ts: the template-literal return type is what makes the dynamic
 * `t('login.ssoError.*')` call typecheck, so a code missing from here would otherwise
 * render as a raw missing-key string.
 *
 * Unknown codes degrade to a generic message rather than throwing, mirroring how
 * lib/logs.ts treats an unrecognised household-log action. That is deliberate: the codes
 * live in the backend (api/v1/oidc.py), so a newer server can name a reason this build has
 * never heard of, and "could not sign you in" beats a blank page or the literal
 * `login.ssoError.whatever`.
 */

const SSO_ERRORS = [
  'no_account',
  'account_disabled',
  'already_linked',
  'state',
  'provider',
] as const

export type SsoError = (typeof SSO_ERRORS)[number]

function isSsoError(value: string): value is SsoError {
  return (SSO_ERRORS as readonly string[]).includes(value)
}

/** The `login.ssoError.*` key for a code from the url, or the fallback for one we do not
 *  recognise. */
export function ssoErrorKey(code: string): `login.ssoError.${SsoError | 'fallback'}` {
  return isSsoError(code) ? `login.ssoError.${code}` : 'login.ssoError.fallback'
}
