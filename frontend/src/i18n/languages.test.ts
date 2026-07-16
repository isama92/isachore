import { describe, expect, it } from 'vitest'
import { DEFAULT_LANGUAGE, isLanguage, LANGUAGES, localeFor } from './languages'

describe('languages', () => {
  it('recognises supported languages and rejects everything else', () => {
    expect(isLanguage('en')).toBe(true)
    expect(isLanguage('it')).toBe(true)
    expect(isLanguage('de')).toBe(false)
    expect(isLanguage(null)).toBe(false)
    expect(isLanguage(42)).toBe(false)
  })

  it('defaults to English', () => {
    expect(DEFAULT_LANGUAGE).toBe('en')
  })

  it('lists both languages with autonym labels', () => {
    expect(LANGUAGES.map((l) => l.id)).toEqual(['en', 'it'])
    expect(LANGUAGES.find((l) => l.id === 'it')?.label).toBe('Italiano')
  })

  it('maps languages to BCP47 locales, falling back to the default for unknown input', () => {
    expect(localeFor('en')).toBe('en-GB')
    expect(localeFor('it')).toBe('it-IT')
    expect(localeFor('xx')).toBe('en-GB')
  })
})
