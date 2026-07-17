import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from '../auth/useAuth'
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
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  return (
    <TooltipProvider delayDuration={0}>
      <SidebarProvider defaultOpen={readSidebarDefaultOpen()}>
        <AppSidebar />
        <SidebarInset>
          <TopBar />
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
