import { afterEach, describe, expect, it, vi } from 'vitest'
import { registerServiceWorker } from './pwa'

function stubServiceWorker(register: () => Promise<unknown>) {
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { register } })
}

/** jsdom reports 'complete'; override to exercise the deferred path too. */
function stubReadyState(value: DocumentReadyState) {
  Object.defineProperty(document, 'readyState', { configurable: true, value })
}

afterEach(() => {
  vi.unstubAllEnvs()
  Reflect.deleteProperty(navigator, 'serviceWorker')
  Reflect.deleteProperty(document, 'readyState')
})

describe('registerServiceWorker', () => {
  it('registers immediately when the page has already loaded', () => {
    // The common case: main.tsx is a deferred module script, so by the time this
    // runs the document can already be complete. Waiting for a `load` that has
    // been and gone would mean never registering.
    vi.stubEnv('PROD', true)
    stubReadyState('complete')
    const register = vi.fn(() => Promise.resolve())
    stubServiceWorker(register)

    registerServiceWorker()

    expect(register).toHaveBeenCalledWith('/sw.js')
  })

  it('defers to load while the page is still loading', () => {
    vi.stubEnv('PROD', true)
    stubReadyState('loading')
    const register = vi.fn(() => Promise.resolve())
    stubServiceWorker(register)

    registerServiceWorker()
    expect(register).not.toHaveBeenCalled()

    window.dispatchEvent(new Event('load'))
    expect(register).toHaveBeenCalledWith('/sw.js')

    // `once`: a second load must not register again.
    window.dispatchEvent(new Event('load'))
    expect(register).toHaveBeenCalledTimes(1)
  })

  it('does nothing in dev, where a worker would break Vite HMR', () => {
    vi.stubEnv('PROD', false)
    stubReadyState('complete')
    const register = vi.fn(() => Promise.resolve())
    stubServiceWorker(register)

    registerServiceWorker()

    expect(register).not.toHaveBeenCalled()
  })

  it('does nothing when the browser has no service worker support', () => {
    vi.stubEnv('PROD', true)
    stubReadyState('complete')
    // navigator.serviceWorker deliberately absent - jsdom's default, and what
    // Safari does in a private window.
    expect(() => registerServiceWorker()).not.toThrow()
  })

  it('swallows a failed registration instead of surfacing it', async () => {
    vi.stubEnv('PROD', true)
    stubReadyState('complete')
    const register = vi.fn(() => Promise.reject(new Error('insecure context')))
    stubServiceWorker(register)

    registerServiceWorker()

    // An unhandled rejection here would fail the suite. Registration fails on
    // plain HTTP, which is a normal state, not something to bother a user with.
    await Promise.resolve()
    expect(register).toHaveBeenCalled()
  })
})
