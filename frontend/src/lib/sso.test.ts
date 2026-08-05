import { describe, expect, it } from 'vitest'
import en from '../i18n/locales/en.json'
import { ssoErrorKey } from './sso'

describe('ssoErrorKey', () => {
  it.each(['no_account', 'account_disabled', 'already_linked', 'state', 'provider'])(
    'maps the %s code to its own key',
    (code) => {
      expect(ssoErrorKey(code)).toBe(`login.ssoError.${code}`)
    },
  )

  it.each(['something_new', '', 'NO_ACCOUNT', '../../etc/passwd', 'fallback'])(
    'degrades %j to the fallback',
    (code) => {
      expect(ssoErrorKey(code)).toBe('login.ssoError.fallback')
    },
  )

  it('produces keys that all exist in en.json', () => {
    // The tuple in sso.ts is a hand-mirror of the ERROR_* constants in
    // backend/app/api/v1/oidc.py, and the keys are a second hand-mirror in en.json.
    // Nothing checks either automatically, so this checks the half that can be: a code
    // listed but not translated would render as a raw missing-key string.
    const codes = [
      'no_account',
      'account_disabled',
      'already_linked',
      'state',
      'provider',
      'anything-unrecognised',
    ]
    const messages = en.login.ssoError as Record<string, string | undefined>
    for (const code of codes) {
      const leaf = ssoErrorKey(code).replace('login.ssoError.', '')
      expect(messages[leaf], `missing en.json copy for ${leaf}`).toBeTruthy()
    }
  })
})
