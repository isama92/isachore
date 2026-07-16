// Supported UI languages. Kept in sync with the Language Literal in
// backend/app/schemas/user.py.
export type Language = 'en' | 'it'

// Drives the language Select on the Profile page. Labels are autonyms (each
// language written in its own name), the convention for language pickers.
export const LANGUAGES: readonly { id: Language; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'it', label: 'Italiano' },
] as const

export const DEFAULT_LANGUAGE: Language = 'en'

const LANGUAGE_IDS = LANGUAGES.map((l) => l.id)

export function isLanguage(v: unknown): v is Language {
  return typeof v === 'string' && (LANGUAGE_IDS as string[]).includes(v)
}

// BCP47 locale used for Intl date/number formatting, per language. Unknown
// input falls back to the default so callers can pass i18n.language raw.
const LOCALES: Record<Language, string> = {
  en: 'en-GB',
  it: 'it-IT',
}

export function localeFor(lang: string): string {
  return isLanguage(lang) ? LOCALES[lang] : LOCALES[DEFAULT_LANGUAGE]
}
