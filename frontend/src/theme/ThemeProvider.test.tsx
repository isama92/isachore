import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ThemeProvider from './ThemeProvider'
import { useTheme } from './useTheme'

function Harness() {
  const { theme, setTheme, accent, setAccent } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="accent">{accent}</span>
      <button onClick={() => setTheme('macchiato')}>set-macchiato</button>
      <button onClick={() => setAccent('mauve')}>set-mauve</button>
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
  it('defaults to Latte + teal when nothing is stored and the OS prefers light', () => {
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('latte')
    expect(screen.getByTestId('accent')).toHaveTextContent('teal')
    expect(document.documentElement).not.toHaveClass('dark')
    expect(document.documentElement.dataset.theme).toBe('latte')
    expect(document.documentElement.dataset.accent).toBe('teal')
  })

  it('defaults to Mocha when the OS prefers dark', () => {
    vi.stubGlobal('matchMedia', matchMediaDark(true))
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('mocha')
    expect(document.documentElement).toHaveClass('dark')
  })

  it('restores the persisted flavour + accent and applies the attributes/class', () => {
    localStorage.setItem('isachore-theme', 'frappe')
    localStorage.setItem('isachore-accent', 'mauve')
    renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('frappe')
    expect(screen.getByTestId('accent')).toHaveTextContent('mauve')
    expect(document.documentElement).toHaveClass('dark')
    expect(document.documentElement.dataset.theme).toBe('frappe')
    expect(document.documentElement.dataset.accent).toBe('mauve')
  })

  it('migrates the old light/dark toggle values onto flavours', () => {
    localStorage.setItem('isachore-theme', 'dark')
    const { unmount } = renderHarness()
    expect(screen.getByTestId('theme')).toHaveTextContent('mocha')
    unmount()

    localStorage.setItem('isachore-theme', 'light')
    renderHarness()
    expect(screen.getAllByTestId('theme')[0]).toHaveTextContent('latte')
  })

  it('sets and persists an explicit flavour + accent choice', async () => {
    const user = userEvent.setup()
    renderHarness()

    await user.click(screen.getByRole('button', { name: 'set-macchiato' }))
    expect(screen.getByTestId('theme')).toHaveTextContent('macchiato')
    expect(document.documentElement).toHaveClass('dark')
    expect(document.documentElement.dataset.theme).toBe('macchiato')
    expect(localStorage.getItem('isachore-theme')).toBe('macchiato')

    await user.click(screen.getByRole('button', { name: 'set-mauve' }))
    expect(screen.getByTestId('accent')).toHaveTextContent('mauve')
    expect(document.documentElement.dataset.accent).toBe('mauve')
    expect(localStorage.getItem('isachore-accent')).toBe('mauve')
  })
})
