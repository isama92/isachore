import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ErrorBoundary from './ErrorBoundary'

function Boom(): never {
  throw new Error('boom')
}

describe('ErrorBoundary', () => {
  it('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <div>All good</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('All good')).toBeInTheDocument()
  })

  it('renders a custom fallback when a child throws', () => {
    // React logs the caught error; silence it for a clean test run.
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary fallback={<div>Custom fallback</div>}>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('Custom fallback')).toBeInTheDocument()
    spy.mockRestore()
  })

  it('shows a reload prompt by default when a child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('heading', { name: 'Something went wrong.' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
    spy.mockRestore()
  })

  it('reloads the page when the default fallback button is clicked', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const original = window.location
    const reload = vi.fn()
    // jsdom's location.reload is a no-op that warns; swap in a spy, then restore.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...original, reload },
    })
    try {
      const user = userEvent.setup()
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      )
      await user.click(screen.getByRole('button', { name: 'Reload' }))
      expect(reload).toHaveBeenCalled()
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original })
      spy.mockRestore()
    }
  })
})
