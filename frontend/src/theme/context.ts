import { createContext } from 'react'

// Catppuccin flavours: Latte is the light theme, the other three are dark.
export type Flavour = 'latte' | 'frappe' | 'macchiato' | 'mocha'

// The 14 named Catppuccin accents. Kept in sync with the Accent Literal in
// backend/app/schemas/user.py and the --ctp-* vars in index.css.
export type Accent =
  | 'rosewater'
  | 'flamingo'
  | 'pink'
  | 'mauve'
  | 'red'
  | 'maroon'
  | 'peach'
  | 'yellow'
  | 'green'
  | 'teal'
  | 'sky'
  | 'sapphire'
  | 'blue'
  | 'lavender'

export type ThemeContextValue = {
  theme: Flavour
  setTheme: (theme: Flavour) => void
  accent: Accent
  setAccent: (accent: Accent) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)
