import * as React from 'react'

const MOBILE_BREAKPOINT = 768

export function useIsMobile() {
  // Lazy initializer reads the viewport once at mount (client-only SPA, so
  // `window` is always present). State then updates only inside the media-query
  // listener, never synchronously in the effect body -- the latter would trip
  // eslint-plugin-react-hooks' set-state-in-effect (see CLAUDE.md).
  const [isMobile, setIsMobile] = React.useState(() => window.innerWidth < MOBILE_BREAKPOINT)

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
