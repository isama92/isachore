import { describe, expect, it } from 'vitest'
import i18n, { changeLanguage } from './i18n'

// The global afterEach in src/test/setup.ts resets the language to English and
// clears localStorage, so each test starts from the English default.
describe('i18n', () => {
  it('starts in English', () => {
    expect(i18n.language).toBe('en')
    expect(i18n.t('common.cancel')).toBe('Cancel')
  })

  it('translates keys into Italian after changeLanguage', async () => {
    await i18n.changeLanguage('it')
    expect(i18n.t('common.cancel')).toBe('Annulla')
    expect(i18n.t('chores.title')).toBe('Gestione faccende')
  })

  it('interpolates variables in both languages', async () => {
    expect(i18n.t('home.credit.doneAs', { name: 'Ada' })).toBe('Done as Ada')
    await i18n.changeLanguage('it')
    expect(i18n.t('home.credit.doneAs', { name: 'Ada' })).toBe('Fatto da Ada')
  })

  it('persists an explicit choice to localStorage and mirrors <html lang>', async () => {
    await changeLanguage('it')
    expect(localStorage.getItem('isachore-language')).toBe('it')
    expect(document.documentElement.lang).toBe('it')
  })

  it('does not persist a bare i18n.changeLanguage (used for resets)', async () => {
    await i18n.changeLanguage('it')
    expect(localStorage.getItem('isachore-language')).toBeNull()
    // <html lang> still tracks the active language for accessibility.
    expect(document.documentElement.lang).toBe('it')
  })
})
