// Apply the saved (or OS-preferred) Catppuccin flavour + accent before first
// paint to avoid a flash. Loaded as a static asset (referenced from index.html)
// so the Content-Security-Policy can stay `script-src 'self'` with no inline
// script. Mirrors src/theme/ThemeProvider.tsx and src/theme/themes.ts -- the
// flavour/accent sets, the dark-flavour set, the legacy light/dark mapping and
// the theme-color bases are duplicated here because this runs before the app
// bundle. Keep in sync.
;(function () {
  try {
    var DARK = { frappe: 1, macchiato: 1, mocha: 1 }
    var FLAVOURS = { latte: 1, frappe: 1, macchiato: 1, mocha: 1 }
    var ACCENTS = {
      rosewater: 1,
      flamingo: 1,
      pink: 1,
      mauve: 1,
      red: 1,
      maroon: 1,
      peach: 1,
      yellow: 1,
      green: 1,
      teal: 1,
      sky: 1,
      sapphire: 1,
      blue: 1,
      lavender: 1,
    }
    var BASE = { latte: '#eff1f5', frappe: '#303446', macchiato: '#24273a', mocha: '#1e1e2e' }

    var stored = localStorage.getItem('isachore-theme')
    var flavour
    if (FLAVOURS[stored]) flavour = stored
    else if (stored === 'light') flavour = 'latte'
    else if (stored === 'dark') flavour = 'mocha'
    else flavour = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'mocha' : 'latte'

    var accent = localStorage.getItem('isachore-accent')
    if (!ACCENTS[accent]) accent = 'teal'

    var root = document.documentElement
    root.dataset.theme = flavour
    root.dataset.accent = accent
    if (DARK[flavour]) root.classList.add('dark')

    var meta = document.querySelector('meta[name="theme-color"]')
    if (meta && BASE[flavour]) meta.setAttribute('content', BASE[flavour])
  } catch (e) {
    /* ignore */
  }
})()
