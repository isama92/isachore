import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import Login from './Login'
import { ApiError } from '../lib/api'
import { renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import { CAPTION_D, HEAD_D } from '../components/brand/paths'

describe('Login', () => {
  it('renders the sign-in form', () => {
    renderWithProviders(<Login />, { route: '/login' })
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText('Welcome back.')).toBeInTheDocument()
  })

  it('shows the brand lockup, including the handwritten caption', () => {
    // The caption was taken out of the sidebar header, so this page is the only
    // place it still appears; losing it here loses it everywhere.
    const { container } = renderWithProviders(<Login />, { route: '/login' })
    expect(screen.getByText('isachore')).toBeInTheDocument()
    expect(container.querySelector('.bg-primary.shadow-logo')).toBeInTheDocument()
    // Assert on the artwork itself rather than counting SVGs: other icons on the
    // page (the remember-me checkbox's tick) would make a count drift.
    const drawn = [...container.querySelectorAll('path')].map((p) => p.getAttribute('d'))
    expect(drawn).toContain(HEAD_D)
    expect(drawn).toContain(CAPTION_D)
  })

  it('renders nothing while auth is loading', () => {
    const { container } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { loading: true },
    })
    expect(container).toBeEmptyDOMElement()
  })

  it('redirects an already-authed user to where they came from', () => {
    const tree = (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dash" element={<div>dash-marker</div>} />
      </Routes>
    )
    renderWithProviders(tree, {
      route: '/login',
      state: { from: '/dash' },
      authValue: { user: makeUser() },
    })
    expect(screen.getByText('dash-marker')).toBeInTheDocument()
  })

  it('submits the credentials and shows a pending state', async () => {
    let resolveLogin: (r: { twoFactorRequired: boolean }) => void = () => {}
    const pending = new Promise<{ twoFactorRequired: boolean }>((resolve) => {
      resolveLogin = resolve
    })
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => pending) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(value.login).toHaveBeenCalledWith('a@example.com', 'password12345', false)
    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled()

    resolveLogin({ twoFactorRequired: false })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled())
  })

  it('passes remember=true when the box is ticked', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => Promise.resolve({ twoFactorRequired: false })) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Remember me' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(value.login).toHaveBeenCalledWith('a@example.com', 'password12345', true)
  })

  it('submits on Enter from the remember-me checkbox without ticking it', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => Promise.resolve({ twoFactorRequired: false })) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    const box = screen.getByRole('checkbox', { name: 'Remember me' })
    box.focus()
    await userEvent.keyboard('{Enter}')

    // Radix would swallow this key outright; the handler hands it back to the form.
    expect(value.login).toHaveBeenCalledWith('a@example.com', 'password12345', false)
    // ...and Enter still must not toggle the box. That part of the Radix behaviour is
    // correct (Space is what toggles a checkbox) and is deliberately kept.
    expect(box).toHaveAttribute('aria-checked', 'false')
  })

  it('still toggles the checkbox on Space, without submitting', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => Promise.resolve({ twoFactorRequired: false })) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    const box = screen.getByRole('checkbox', { name: 'Remember me' })
    box.focus()
    await userEvent.keyboard(' ')

    // Pins the `e.key !== 'Enter'` guard. Broaden or drop it and Space starts submitting
    // the form instead of ticking the box, breaking the standard checkbox interaction for
    // every keyboard user.
    expect(box).toHaveAttribute('aria-checked', 'true')
    expect(value.login).not.toHaveBeenCalled()
  })

  // requestSubmit() consults no button, so unlike implicit submission it is NOT stopped by
  // the disabled Sign in button. Two clauses stand in for that, and they cover different
  // moments, so they get a test each.
  it('ignores the auto-repeat of a held Enter', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => new Promise<never>(() => {})) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    const box = screen.getByRole('checkbox', { name: 'Remember me' })
    box.focus()
    // userEvent does not set the repeat flag even for a held key, so this is fireEvent:
    // `repeat: true` is precisely what a real browser sends from the second keydown on,
    // and it is the only signal available before React has re-rendered with `submitting`.
    fireEvent.keyDown(box, { key: 'Enter', repeat: true })

    expect(value.login).not.toHaveBeenCalled()
  })

  it('ignores a second Enter while the first login is still in flight', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => new Promise<never>(() => {})) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    screen.getByRole('checkbox', { name: 'Remember me' }).focus()
    await userEvent.keyboard('{Enter}{Enter}')

    // `login` never resolves, so `submitting` stays true: the second press must be a
    // no-op rather than a second POST into the Redis login throttle.
    expect(value.login).toHaveBeenCalledTimes(1)
  })

  it('does not submit on Enter from the checkbox while a field is empty', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => Promise.resolve({ twoFactorRequired: false })) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    screen.getByRole('checkbox', { name: 'Remember me' }).focus()
    await userEvent.keyboard('{Enter}')

    // The password field is `required`, so the browser blocks this exactly as it blocks
    // Enter in the email field. Pins requestSubmit() over calling the submit handler
    // directly: the latter would skip constraint validation and post an empty password.
    expect(value.login).not.toHaveBeenCalled()
  })

  it('shows the code step and verifies when 2FA is required', async () => {
    const verifyTwoFactor = vi.fn(async () => {})
    renderWithProviders(<Login />, {
      route: '/login',
      authValue: {
        login: vi.fn(async () => ({ twoFactorRequired: true })),
        verifyTwoFactor,
      },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    // The password form is replaced by the code step.
    const codeInput = await screen.findByLabelText('Authentication code')
    await userEvent.type(codeInput, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))

    expect(verifyTwoFactor).toHaveBeenCalledWith('123456')
  })

  it('lets the user switch to a recovery code on the 2FA step', async () => {
    renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(async () => ({ twoFactorRequired: true })) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await screen.findByLabelText('Authentication code')
    await userEvent.click(screen.getByRole('button', { name: 'Use a recovery code instead' }))
    expect(screen.getByLabelText('Recovery code')).toBeInTheDocument()
  })

  it('shows an error when the 2FA code is rejected', async () => {
    renderWithProviders(<Login />, {
      route: '/login',
      authValue: {
        login: vi.fn(async () => ({ twoFactorRequired: true })),
        verifyTwoFactor: vi.fn().mockRejectedValue(new ApiError(401, 'Invalid or expired code')),
      },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await userEvent.type(await screen.findByLabelText('Authentication code'), '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))

    expect(await screen.findByText('Invalid or expired code')).toBeInTheDocument()
  })

  it('shows the API error message on a failed login', async () => {
    renderWithProviders(<Login />, {
      route: '/login',
      authValue: {
        login: vi.fn().mockRejectedValue(new ApiError(401, 'Invalid email or password')),
      },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument()
  })

  it('shows a generic message on an unexpected error', async () => {
    renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn().mockRejectedValue(new Error('network down')) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Something went wrong, please try again')).toBeInTheDocument()
  })
})
