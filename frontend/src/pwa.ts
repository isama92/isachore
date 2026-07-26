/**
 * Service worker registration, kept out of main.tsx so it can be tested (main.tsx
 * is excluded from coverage in vite.config.ts).
 *
 * Production only, deliberately: in dev a service worker intercepts the very
 * requests Vite's HMR depends on, so the page starts serving stale modules and
 * the reason is never obvious. See public/sw.js for what it does and does not
 * cache.
 */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return
  if (!('serviceWorker' in navigator)) return

  const register = () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // A failed registration costs the offline shell and the install prompt,
      // nothing else -- the app works normally without it, so there is nothing
      // useful to tell the user here.
    })
  }

  // Wait for load so registration never competes with the first render for
  // bandwidth on a phone. But `load` fires once and never again, so if the page
  // has already finished by the time this runs, waiting would mean never
  // registering at all -- hence the readyState check rather than a bare
  // listener. `once` because registering twice is pointless.
  if (document.readyState === 'complete') register()
  else window.addEventListener('load', register, { once: true })
}
