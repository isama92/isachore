import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { routes } from '../lib/routes'
import AppSidebar from './AppSidebar'
import TopBar from './TopBar'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'

// shadcn's SidebarProvider writes the open/closed state to the `sidebar_state`
// cookie but relies on a server to read it back into `defaultOpen`. This is a
// client-only SPA, so we read the cookie here to restore the last desktop
// state across reloads (absent cookie -> open, matching the shadcn default).
function readSidebarDefaultOpen(): boolean {
  const match = document.cookie.match(/(?:^|;\s*)sidebar_state=([^;]+)/)
  return match ? match[1] === 'true' : true
}

export default function RequireAuth() {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return null
  if (!user) return <Navigate to={routes.login} replace state={{ from: location.pathname }} />

  return (
    <TooltipProvider delayDuration={0}>
      <SidebarProvider defaultOpen={readSidebarDefaultOpen()}>
        <AppSidebar />
        <SidebarInset>
          <TopBar />
          {/* Keyed so that switching identity (impersonation starting or stopping)
              tears the page down and mounts it again. Nothing else would: `refresh()`
              updates the auth context and clears the remembered table settings, but no
              page's load effect depends on the context - `useServerTable`'s fetch
              deliberately does not, and Home and Unscheduled lazy-initialise their
              assignee filter from `user.id` exactly once. Without this the admin
              returning from an impersonated session keeps that person's rows on screen
              until they navigate away by hand. The key is `user.id`, NOT the user
              object: a profile save calls `refresh()` too, and must not throw the page
              away. */}
          <Outlet key={user.id} />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
