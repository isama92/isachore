import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
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
