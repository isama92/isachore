import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { THEMES, ACCENTS, DEFAULT_ACCENT } from './themes'

// public/theme-init.js runs before the app bundle (pre-paint theme guard) so it
// can't import this module and duplicates the flavour/accent sets by hand. It
// lives outside eslint/tsc scope, so guard against the two drifting apart: every
// flavour and accent defined here must still appear in that file.
const themeInitPath = join(dirname(fileURLToPath(import.meta.url)), '../../public/theme-init.js')
const themeInit = readFileSync(themeInitPath, 'utf8')

describe('public/theme-init.js stays in sync with themes.ts', () => {
  it('references every flavour', () => {
    for (const theme of THEMES) expect(themeInit).toContain(`${theme.id}:`)
  })

  it('references every accent', () => {
    for (const accent of ACCENTS) expect(themeInit).toContain(`${accent.id}:`)
  })

  it('uses the same default accent', () => {
    expect(themeInit).toContain(`accent = '${DEFAULT_ACCENT}'`)
  })
})
