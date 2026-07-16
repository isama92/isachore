import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { DEFAULT_LANGUAGE, isLanguage, LANGUAGES, type Language } from './languages'
import en from './locales/en.json'
import it from './locales/it.json'

const LANGUAGE_KEY = 'isachore-language'

// Read the persisted language, else fall back to the default (English). Runs
// before init so the first render is already in the right language. English is
// the deliberate default here (no navigator detection, unlike the theme which
// follows the OS).
function getInitialLanguage(): Language {
  const stored = localStorage.getItem(LANGUAGE_KEY)
  return isLanguage(stored) ? stored : DEFAULT_LANGUAGE
}

// Keep <html lang> in step with the active language (mirrors the ThemeProvider
// DOM effect). This intentionally does NOT persist: like setTheme, persistence
// happens only on an explicit choice via changeLanguage() below, so a
// programmatic reset (or the initial default) never writes localStorage.
i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng
})

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    it: { translation: it },
  },
  lng: getInitialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: LANGUAGES.map((l) => l.id),
  // React already escapes rendered values, so i18next must not double-escape.
  interpolation: { escapeValue: false },
  // Resources are bundled synchronously, so there is nothing to suspend on;
  // disabling Suspense avoids needing a boundary the app does not have.
  react: { useSuspense: false },
})

// Change the language and persist the explicit choice (the counterpart to the
// theme provider's setTheme). Use this everywhere the user picks a language or
// we adopt their saved one; call i18n.changeLanguage directly only for a
// non-persisting reset (e.g. test teardown).
export function changeLanguage(lng: Language): Promise<unknown> {
  localStorage.setItem(LANGUAGE_KEY, lng)
  return i18n.changeLanguage(lng)
}

export default i18n

// Typed translation keys: `t('bad.key')` becomes a compile error and a key that
// exists in en.json but is never used still typechecks. en.json is the source
// of truth for the key set; it.json must mirror it.
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation'
    resources: {
      translation: typeof en
    }
  }
}
