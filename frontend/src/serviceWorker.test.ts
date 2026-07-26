import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createContext, runInContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

// public/sw.js is a classic worker script: it cannot be imported, and asserting
// on its source text only proves a string exists, not that the guard runs. So
// evaluate it against a fake `self` and drive real events through it. That is
// what makes the caching rules below actually enforced rather than merely
// written down -- and the /api/ exclusion in particular is privacy-load-bearing.
const swSource = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../public/sw.js'),
  'utf8',
)
const CACHE_NAME = /const CACHE = '([^']+)'/.exec(swSource)![1]
const ORIGIN = 'https://isachore.example.com'

type FakeResponse = {
  ok: boolean
  redirected: boolean
  body: string
  headers: { get(name: string): string | null }
  clone(): FakeResponse
}

function response({ ok = true, redirected = false, type = 'text/html', body = 'shell' } = {}) {
  const r: FakeResponse = {
    ok,
    redirected,
    body,
    headers: { get: (n) => (n.toLowerCase() === 'content-type' ? type : null) },
    clone: () => r,
  }
  return r
}

type Keyable = string | { url: string }
const keyOf = (k: Keyable) => (typeof k === 'string' ? k : new URL(k.url).pathname)

function makeCaches() {
  const store = new Map<string, Map<string, FakeResponse>>()
  const open = async (name: string) => {
    if (!store.has(name)) store.set(name, new Map())
    const entries = store.get(name)!
    return {
      put: async (k: Keyable, v: FakeResponse) => void entries.set(keyOf(k), v),
      add: async (k: Keyable) => void entries.set(keyOf(k), response()),
      match: async (k: Keyable) => entries.get(keyOf(k)),
    }
  }
  const api = {
    open,
    keys: async () => [...store.keys()],
    delete: async (n: string) => store.delete(n),
    match: async (k: Keyable) => {
      for (const entries of store.values()) {
        const hit = entries.get(keyOf(k))
        if (hit) return hit
      }
      return undefined
    },
  }
  return { api, store }
}

type Handler = (event: Record<string, unknown>) => void
/** The worker only ever calls fetch(request) and gets a response back. */
type FetchMock = Mock<(request: unknown) => Promise<FakeResponse>>

function loadWorker(fetchImpl: FetchMock) {
  const handlers: Record<string, Handler> = {}
  const { api: cachesApi, store } = makeCaches()
  const fakeSelf = {
    addEventListener: (type: string, fn: Handler) => void (handlers[type] = fn),
    location: { origin: ORIGIN },
    skipWaiting: vi.fn(async () => {}),
    clients: { claim: vi.fn(async () => {}) },
  }
  const ResponseStub = { error: () => response({ ok: false, body: 'network-error' }) }
  // A worker global is only what we hand it: anything sw.js reaches for that is
  // not here is undefined, which is itself part of the test. Promise is passed in
  // so the worker's promises live in this realm and `await` below behaves.
  const context = createContext({
    self: fakeSelf,
    caches: cachesApi,
    fetch: fetchImpl,
    Response: ResponseStub,
    URL,
    Promise,
  })
  runInContext(swSource, context)
  return { handlers, store, fakeSelf }
}

function request(path: string, { method = 'GET', mode = 'no-cors', origin = ORIGIN } = {}) {
  return { url: origin + path, method, mode }
}

function fetchEvent(req: ReturnType<typeof request>) {
  const waits: Promise<unknown>[] = []
  let responded: Promise<FakeResponse> | undefined
  return {
    request: req,
    respondWith(p: Promise<FakeResponse>) {
      responded = Promise.resolve(p)
    },
    waitUntil(p: Promise<unknown>) {
      waits.push(Promise.resolve(p))
    },
    get responded() {
      return responded
    },
    /** Let the cache writes handed to waitUntil finish. */
    settle: () => Promise.all(waits),
  }
}

/** Boot a worker with its install step done, so the shell is already cached. */
async function boot(fetchImpl: FetchMock = vi.fn()) {
  const worker = loadWorker(fetchImpl)
  const waits: Promise<unknown>[] = []
  worker.handlers.install({ waitUntil: (p: Promise<unknown>) => void waits.push(p) })
  await Promise.all(waits)
  return worker
}

const shellIn = (store: Map<string, Map<string, FakeResponse>>) =>
  store.get(CACHE_NAME)?.get('/index.html')

describe('the service worker leaves alone what it must not touch', () => {
  it('never intercepts /api/, so no authenticated response can be cached', async () => {
    const { handlers } = await boot()
    const event = fetchEvent(request('/api/v1/chores'))

    handlers.fetch(event)

    expect(event.responded).toBeUndefined()
  })

  it('never intercepts a non-GET request', async () => {
    const { handlers } = await boot()
    const event = fetchEvent(request('/assets/app.js', { method: 'POST' }))

    handlers.fetch(event)

    expect(event.responded).toBeUndefined()
  })

  it('never intercepts a cross-origin request', async () => {
    const { handlers } = await boot()
    const event = fetchEvent(request('/assets/app.js', { origin: 'https://elsewhere.example' }))

    handlers.fetch(event)

    expect(event.responded).toBeUndefined()
  })
})

describe('the service worker, on a navigation', () => {
  async function navigate(fetchImpl: FetchMock) {
    const worker = await boot(fetchImpl)
    const event = fetchEvent(request('/chores', { mode: 'navigate' }))
    worker.handlers.fetch(event)
    const result = await event.responded
    await event.settle()
    return { ...worker, result }
  }

  it('serves the network response and caches it as the new shell', async () => {
    const fresh = response({ body: 'fresh-html' })
    const { store, result } = await navigate(vi.fn(async () => fresh))

    expect(result?.body).toBe('fresh-html')
    expect(shellIn(store)?.body).toBe('fresh-html')
  })

  it('does NOT cache an HTTP error as the shell', async () => {
    // fetch() rejects on a network error but not on an HTTP one, so a 502 from
    // the proxy during a rolling restart arrives here as a resolved response.
    // Caching it would pin a gateway error as the offline shell.
    const { store, result } = await navigate(
      vi.fn(async () => response({ ok: false, body: '502 Bad Gateway' })),
    )

    expect(result?.body).toBe('502 Bad Gateway') // still passed through to the page
    expect(shellIn(store)?.body).toBe('shell') // but the good shell survives
  })

  it('does NOT cache a non-HTML body as the shell', async () => {
    // Navigating straight to an asset URL is still mode: 'navigate'.
    const { store } = await navigate(
      vi.fn(async () => response({ type: 'image/svg+xml', body: '<svg/>' })),
    )

    expect(shellIn(store)?.body).toBe('shell')
  })

  it('does NOT cache a redirected response', async () => {
    // Replaying one for a navigation makes the browser fail the navigation with
    // "a redirected response was used for a request whose redirect mode is not
    // follow", which would break the app offline rather than degrade it.
    const { store } = await navigate(
      vi.fn(async () => response({ redirected: true, body: 'redirected' })),
    )

    expect(shellIn(store)?.body).toBe('shell')
  })

  it('falls back to the cached shell when the network is gone', async () => {
    const { result } = await navigate(vi.fn(async () => Promise.reject(new Error('offline'))))

    expect(result?.body).toBe('shell')
  })
})

describe('the service worker, on a hashed asset', () => {
  it('fetches and caches it on a miss, then serves it without the network', async () => {
    const fetchImpl = vi.fn(async () => response({ type: 'text/javascript', body: 'bundle' }))
    const { handlers, store } = await boot(fetchImpl)

    const miss = fetchEvent(request('/assets/index-abc123.js'))
    handlers.fetch(miss)
    expect((await miss.responded)?.body).toBe('bundle')
    await miss.settle()
    expect(store.get(CACHE_NAME)?.get('/assets/index-abc123.js')?.body).toBe('bundle')

    const hit = fetchEvent(request('/assets/index-abc123.js'))
    handlers.fetch(hit)
    expect((await hit.responded)?.body).toBe('bundle')
    expect(fetchImpl).toHaveBeenCalledTimes(1) // served from cache, not refetched
  })

  it('does not cache a failed asset fetch', async () => {
    const { handlers, store } = await boot(vi.fn(async () => response({ ok: false, body: '404' })))
    const event = fetchEvent(request('/assets/missing.js'))

    handlers.fetch(event)
    await event.responded
    await event.settle()

    expect(store.get(CACHE_NAME)?.has('/assets/missing.js')).toBe(false)
  })
})

describe('the service worker lifecycle', () => {
  it('drops caches from older versions on activate', async () => {
    const { handlers, store, fakeSelf } = await boot()
    store.set('isachore-shell-vOLD', new Map())

    const waits: Promise<unknown>[] = []
    handlers.activate({ waitUntil: (p: Promise<unknown>) => void waits.push(p) })
    await Promise.all(waits)

    expect([...store.keys()]).toEqual([CACHE_NAME])
    expect(fakeSelf.clients.claim).toHaveBeenCalled()
  })

  it('takes over immediately rather than waiting for every tab to close', async () => {
    const { fakeSelf } = await boot()
    expect(fakeSelf.skipWaiting).toHaveBeenCalled()
  })
})
