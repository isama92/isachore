import { describe, expect, it } from 'vitest'
import i18n from '../i18n/i18n'
import { logActionLabel, logFieldLabel } from './logs'
import { LOG_ACTIONS, LOG_FIELDS } from './types'

const t = i18n.t.bind(i18n)

describe('logActionLabel', () => {
  it('names every action in the closed set', () => {
    for (const action of LOG_ACTIONS) {
      const label = logActionLabel(t, action)
      expect(label).not.toContain('logs.actions')
      expect(label).not.toBe(action)
    }
  })

  it('opens up the underscores of an action it does not know', () => {
    // A newer server writing an action an older client is reading - which a cached
    // service-worker shell makes reachable. Anything beats echoing the translation key.
    expect(logActionLabel(t, 'chore_archived')).toBe('chore archived')
  })
})

describe('logFieldLabel', () => {
  it('names every field in the closed set', () => {
    for (const field of LOG_FIELDS) {
      const label = logFieldLabel(t, field)
      expect(label).not.toContain('logs.fields')
      expect(label).not.toBe(field)
    }
  })

  it('opens up the underscores of a field it does not know', () => {
    expect(logFieldLabel(t, 'nickname_colour')).toBe('nickname colour')
  })
})

describe('in Italian', () => {
  it('translates an action and a field', async () => {
    // Bare changeLanguage, not the persisting wrapper: this is a test-local switch, not a
    // choice worth remembering.
    await i18n.changeLanguage('it')
    try {
      expect(logActionLabel(t, 'chore_created')).toBe('Faccenda creata')
      expect(logFieldLabel(t, 'start_date')).toBe('Data di inizio')
    } finally {
      await i18n.changeLanguage('en')
    }
  })
})
