import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ThemeProvider from './ThemeProvider'
import { useTheme } from './useTheme'

function Harness() {
  const { theme, toggleTheme } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={toggleTheme}>toggle</button>
    </div>
  )
}

function renderHarness() {
  return render(
    <ThemeProvider>
      <Harness />
    </ThemeProvider>,
  )
}

function matchMediaDark(matches: boolean) {
  return (query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}

describe('ThemeProvider', () => {
  it('defaults to light when nothing is stored and the OS prefers light', () => {
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('restores the persisted theme and applies the class', () => {
    localStorage.setItem('isachore-theme', 'dark')
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('dark')
    expect(document.documentElement).toHaveClass('dark')
  })

  it('falls back to the OS preference when nothing is stored', () => {
    vi.stubGlobal('matchMedia', matchMediaDark(true))
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('dark')
  })

  it('toggles and persists the choice', async () => {
    const user = userEvent.setup()
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('light')

    await user.click(screen.getByRole('button', { name: 'toggle' }))

    expect(screen.getByTestId('theme')).toHaveTextContent('dark')
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('isachore-theme')).toBe('dark')
  })
})
