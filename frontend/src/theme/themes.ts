import type { Accent, Flavour } from './context'

export type ThemeGroup = 'light' | 'dark'

export type ThemeMeta = {
  id: Flavour
  label: string
  group: ThemeGroup
  // Whether this theme exposes an accent-colour choice. All Catppuccin flavours
  // do; the flag exists so a future theme can opt out and hide the picker.
  supportsAccent: boolean
}

// Drives the grouped Select on the Profile page (and the light/dark split).
export const THEMES: readonly ThemeMeta[] = [
  { id: 'latte', label: 'Catppuccin Latte', group: 'light', supportsAccent: true },
  { id: 'frappe', label: 'Catppuccin Frappé', group: 'dark', supportsAccent: true },
  { id: 'macchiato', label: 'Catppuccin Macchiato', group: 'dark', supportsAccent: true },
  { id: 'mocha', label: 'Catppuccin Mocha', group: 'dark', supportsAccent: true },
] as const

// Drives the accent swatch grid; order is the display order. Each swatch draws
// its colour from the CSS var --ctp-<id> (defined per flavour in index.css), so
// no hex lives here.
export const ACCENTS: readonly { id: Accent; label: string }[] = [
  { id: 'rosewater', label: 'Rosewater' },
  { id: 'flamingo', label: 'Flamingo' },
  { id: 'pink', label: 'Pink' },
  { id: 'mauve', label: 'Mauve' },
  { id: 'red', label: 'Red' },
  { id: 'maroon', label: 'Maroon' },
  { id: 'peach', label: 'Peach' },
  { id: 'yellow', label: 'Yellow' },
  { id: 'green', label: 'Green' },
  { id: 'teal', label: 'Teal' },
  { id: 'sky', label: 'Sky' },
  { id: 'sapphire', label: 'Sapphire' },
  { id: 'blue', label: 'Blue' },
  { id: 'lavender', label: 'Lavender' },
] as const

export const DEFAULT_LIGHT: Flavour = 'latte'
export const DEFAULT_DARK: Flavour = 'mocha'
export const DEFAULT_ACCENT: Accent = 'teal'

const FLAVOURS = THEMES.map((t) => t.id)
const ACCENT_IDS = ACCENTS.map((a) => a.id)

export function isFlavour(v: unknown): v is Flavour {
  return typeof v === 'string' && (FLAVOURS as string[]).includes(v)
}

export function isAccent(v: unknown): v is Accent {
  return typeof v === 'string' && (ACCENT_IDS as string[]).includes(v)
}

export function isDark(flavour: Flavour): boolean {
  return THEMES.find((t) => t.id === flavour)?.group === 'dark'
}

export function supportsAccent(flavour: Flavour): boolean {
  return !!THEMES.find((t) => t.id === flavour)?.supportsAccent
}

// Map the OLD light/dark toggle's stored value onto a flavour so existing users
// don't flash or break on the first load after this ships. Anything that isn't
// a legacy value returns null ("no stored choice, follow the OS").
export function migrateLegacy(value: string | null): Flavour | null {
  if (value === 'light') return DEFAULT_LIGHT
  if (value === 'dark') return DEFAULT_DARK
  return null
}
