import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import Login from './Login'
import { ApiError } from '../lib/api'
import { mockFetch, renderWithProviders } from '../test/utils'
import { makeUser } from '../test/fixtures'
import { CAPTION_D, HEAD_D } from '../components/brand/paths'
import type { AuthMethods } from '../lib/types'

const PASSWORD_ONLY: AuthMethods = {
  password_enabled: true,
  oidc_enabled: false,
  oidc_provider_name: null,
}

const WITH_PROVIDER: AuthMethods = {
  password_enabled: true,
  oidc_enabled: true,
  oidc_provider_name: 'Authentik',
}

/** Stub GET /auth/methods, the page's one request. */
function stubMethods(methods: AuthMethods) {
  return mockFetch([{ path: '/api/v1/auth/methods', body: methods }])
}

describe('Login', () => {
  // The page probes which sign-in methods exist on mount. Every case needs the stub, or
  // it falls back to password-only via a rejected request - which happens to be the right
  // answer for most of them and so would hide a broken probe rather than exercise it.
  beforeEach(() => {
    stubMethods(PASSWORD_ONLY)
  })

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

  describe('single sign-on', () => {
    it('offers no provider button when none is configured', async () => {
      renderWithProviders(<Login />, { route: '/login' })

      // Awaited, so the probe has resolved: asserting absence before it answers would
      // pass whatever the payload said.
      expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: /Sign in with/ })).not.toBeInTheDocument()
    })

    it('offers the provider button, labelled from the server', async () => {
      stubMethods(WITH_PROVIDER)
      renderWithProviders(<Login />, { route: '/login' })

      const link = await screen.findByRole('link', { name: 'Sign in with Authentik' })
      // An anchor, not a button: the flow is a full-page navigation to our own backend,
      // which then redirects to the provider. A fetch could not do this - the prod CSP
      // forbids connect-src to another origin - and a submit button inside the form would
      // hijack the Enter key.
      expect(link).toHaveAttribute(
        'href',
        `/api/v1/auth/oidc/start?return_to=${encodeURIComponent('/')}`,
      )
    })

    it.each([
      ['an empty name', ''],
      ['a whitespace-only name', '   '],
      ['no name at all', null],
    ])('falls back to a generic label given %s', async (_why, name) => {
      // The server guarantees a usable name, so this is the belt to that braces - a client
      // cannot know which server version it is talking to. Falling back rather than hiding
      // matters because under OIDC_ONLY the credential form is gone too, so hiding would
      // leave a login page with no way in at all.
      stubMethods({ ...WITH_PROVIDER, oidc_provider_name: name })
      renderWithProviders(<Login />, { route: '/login' })

      expect(await screen.findByRole('link', { name: 'Sign in with SSO' })).toBeInTheDocument()
    })

    it('always offers a way in, even with no password form and no provider name', async () => {
      // The combination that used to render nothing at all: OIDC_ONLY hides the form, and a
      // blank name used to hide the button.
      stubMethods({ password_enabled: false, oidc_enabled: true, oidc_provider_name: '' })
      renderWithProviders(<Login />, { route: '/login' })

      expect(await screen.findByRole('link', { name: 'Sign in with SSO' })).toBeInTheDocument()
      expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    })

    it('carries where the visitor was headed through the provider round trip', async () => {
      stubMethods(WITH_PROVIDER)
      // Router state cannot survive a full-page navigation away and back, so the return
      // target has to ride in the query string instead.
      renderWithProviders(<Login />, { route: '/login', state: { from: '/chores?page=2' } })

      const link = await screen.findByRole('link', { name: 'Sign in with Authentik' })
      expect(link).toHaveAttribute(
        'href',
        `/api/v1/auth/oidc/start?return_to=${encodeURIComponent('/chores?page=2')}`,
      )
    })

    it('hides the credential form when the server has disabled password sign-in', async () => {
      stubMethods({ ...WITH_PROVIDER, password_enabled: false })
      renderWithProviders(<Login />, { route: '/login' })

      expect(
        await screen.findByRole('link', { name: 'Sign in with Authentik' }),
      ).toBeInTheDocument()
      expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
      expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
    })

    it('still shows the credential form when the probe fails', async () => {
      // Fail-open. Note this is pinned by the password-only *initial state* rather than by
      // the catch, which has nothing to put back: leaving the request unhandled and
      // handling it both land here, which is precisely why the fallback is the default
      // rather than something the error path assigns.
      mockFetch([{ path: '/api/v1/auth/methods', status: 500, body: { detail: 'boom' } }])
      renderWithProviders(<Login />, { route: '/login' })

      expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
      expect(screen.getByLabelText('Email')).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: /Sign in with/ })).not.toBeInTheDocument()
    })

    it.each([
      ['no_account', 'No isachore account exists for that address.'],
      ['email_unverified', 'Your email address has not been verified'],
      ['account_disabled', 'This isachore account has been deactivated.'],
      ['already_linked', 'That address is already linked to a different sign-in account.'],
      ['state', 'That sign-in attempt expired or could not be verified.'],
      ['provider', 'Could not finish signing in with your provider.'],
    ])('explains a refused sign-on: %s', async (code, expected) => {
      stubMethods(WITH_PROVIDER)
      renderWithProviders(<Login />, { route: `/login?sso_error=${code}` })

      expect(
        await screen.findByText(new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))),
      ).toBeInTheDocument()
    })

    it('degrades an sso_error code it does not recognise', async () => {
      // The codes live in the backend, so a newer server can name a reason this build has
      // never heard of. That must read as an apology, not as a missing-key string.
      stubMethods(WITH_PROVIDER)
      renderWithProviders(<Login />, { route: '/login?sso_error=something_new' })

      expect(
        await screen.findByText('Could not sign you in. Please try again.'),
      ).toBeInTheDocument()
      expect(screen.queryByText(/login\.ssoError/)).not.toBeInTheDocument()
    })

    it('shows a refusal even with the credential form hidden', async () => {
      // Under OIDC_ONLY the error has no form to sit inside, so it needs its own slot.
      stubMethods({ ...WITH_PROVIDER, password_enabled: false })
      renderWithProviders(<Login />, { route: '/login?sso_error=no_account' })

      // Wait for the probe to settle FIRST. Until it answers the page assumes password
      // sign-in is available, so the error is briefly rendered inside the credential form;
      // querying before that resolves hands back an element the re-render then detaches,
      // which fails on the wrong thing and looks like the error is missing.
      await screen.findByRole('link', { name: 'Sign in with Authentik' })
      expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
      expect(screen.getByText(/No isachore account exists for that address/)).toBeInTheDocument()
    })

    it('clears a refusal once the visitor tries again', async () => {
      // Held in the same state as a form error precisely so this happens: a stale reason
      // must not linger under a fresh attempt.
      renderWithProviders(<Login />, {
        route: '/login?sso_error=no_account',
        authValue: { login: vi.fn().mockResolvedValue({ twoFactorRequired: false }) },
      })

      expect(
        await screen.findByText(/No isachore account exists for that address/),
      ).toBeInTheDocument()

      await userEvent.type(screen.getByLabelText('Email'), 'a@example.com')
      await userEvent.type(screen.getByLabelText('Password'), 'password12345')
      await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

      await waitFor(() =>
        expect(
          screen.queryByText(/No isachore account exists for that address/),
        ).not.toBeInTheDocument(),
      )
    })
  })
})
