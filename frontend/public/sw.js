// Service worker: an offline app shell, and the thing Chrome requires before it
// will offer to install the app. Hand-written rather than generated, because the
// only asset that needs care is index.html -- everything Vite emits under
// /assets/ is content-hashed, so those URLs are immutable and safe to keep
// forever. Registered from src/pwa.ts, and only in a production build.
//
// It deliberately caches NOTHING from /api/. Every API response here is
// authenticated and full of household data, and the app has no offline write
// model, so caching it would put personal data on the device to no benefit. The
// consequence worth knowing: logging out leaves nothing behind, because nothing
// personal was ever stored.
//
// Bump CACHE when this file changes: `activate` then drops every other cache.
//
// Note what that does NOT cover. This file is byte-identical across ordinary
// deploys, so no new worker activates and nothing is ever pruned, which means
// each deploy's hashed /assets/ accumulate in the one cache. That is left to the
// browser's storage eviction on purpose: it is roughly a megabyte per deploy
// against an origin quota in the hundreds, and pruning it properly needs the
// build integration this worker exists to avoid.
const CACHE = 'isachore-shell-v1'
const SHELL = '/index.html'

// Cache writes are fire-and-forget as far as the response is concerned, but they
// still have to be handed to waitUntil, or the worker can be terminated before
// the write lands. The catch matters too: a rejection (storage quota, or a
// response the Cache API refuses to store) would otherwise surface as an
// unhandled rejection inside the worker.
function cachePut(event, key, response) {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.put(key, response))
      .catch(() => {}),
  )
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // Anything that could carry user data or change state goes straight to the
  // network, untouched and uncached.
  if (request.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  // Navigations: network first, so a deployed update is picked up as soon as the
  // device is online, with the cached shell as the offline fallback.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Only a good HTML response is allowed to become the offline shell.
          // fetch() rejects on a network error but NOT on an HTTP error, so a 502
          // from the proxy during a rolling restart resolves normally, and without
          // this it would be pinned as the shell until the next successful
          // navigation. The content-type check covers navigating straight to an
          // asset URL, and `redirected` has to be excluded because replaying a
          // redirected response for a navigation makes the browser fail it.
          const type = response.headers.get('content-type') || ''
          if (response.ok && !response.redirected && type.includes('text/html')) {
            cachePut(event, SHELL, response.clone())
          }
          return response
        })
        .catch(() => caches.match(SHELL).then((hit) => hit || Response.error())),
    )
    return
  }

  // Hashed build output: cache first. The filename changes when the content
  // does, so a hit can never be stale.
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) cachePut(event, request, response.clone())
            return response
          }),
      ),
    )
  }
})
