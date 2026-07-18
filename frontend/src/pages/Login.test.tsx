import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import Login from './Login'
import { ApiError } from '../lib/api'
import { renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'

describe('Login', () => {
  it('renders the sign-in form', () => {
    renderWithProviders(<Login />, { route: '/login' })
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText('Welcome back.')).toBeInTheDocument()
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
    let resolveLogin: () => void = () => {}
    const pending = new Promise<void>((resolve) => {
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

    resolveLogin()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled())
  })

  it('passes remember=true when the box is ticked', async () => {
    const { value } = renderWithProviders(<Login />, {
      route: '/login',
      authValue: { login: vi.fn(() => Promise.resolve()) },
    })

    await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'password12345')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Remember me' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(value.login).toHaveBeenCalledWith('a@example.com', 'password12345', true)
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
