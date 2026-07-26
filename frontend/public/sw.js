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
// Bump CACHE when this file changes; `activate` deletes every other cache.
const CACHE = 'isachore-shell-v1'
const SHELL = '/index.html'

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
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put(SHELL, copy))
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
            if (response.ok) {
              const copy = response.clone()
              caches.open(CACHE).then((cache) => cache.put(request, copy))
            }
            return response
          }),
      ),
    )
  }
})
