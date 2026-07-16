import { useTranslation } from 'react-i18next'
import { changeLanguage } from './i18n'
import { DEFAULT_LANGUAGE, isLanguage, type Language } from './languages'

// The current language plus a setter, mirroring useTheme()'s shape. Reading
// through useTranslation() re-renders consumers when the language changes;
// setLanguage persists the choice (localStorage) and the languageChanged
// listener in i18n.ts mirrors it onto <html lang>.
export function useLanguage() {
  const { i18n } = useTranslation()
  const language: Language = isLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE
  const setLanguage = (next: Language) => {
    void changeLanguage(next)
  }
  return { language, setLanguage }
}
