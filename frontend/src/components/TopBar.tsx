import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { api } from '../lib/api'
import { Button } from '@/components/ui/button'

export default function TopBar() {
  const { user, impersonating, logout, refresh } = useAuth()
  if (!user) return null

  async function returnToAdmin() {
    try {
      await api.post('/api/v1/auth/stop-impersonating')
    } catch {
      // If the parked admin session has expired the server ends both sessions
      // and returns 401; refresh() below then reflects the logged-out state and
      // RequireAuth sends the operator to login.
    } finally {
      await refresh()
    }
  }

  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3">
        <Link to="/" className="flex items-center gap-2">
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-sm font-extrabold text-white shadow-logo">
            ✓
          </span>
          <span className="font-display text-lg font-extrabold tracking-tight">isachore</span>
        </Link>
        <nav className="flex items-center gap-4">
          {impersonating && (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              className="rounded-full font-bold"
              onClick={() => void returnToAdmin()}
            >
              Return to admin
            </Button>
          )}
          <Link to="/chores" className="text-sm font-bold text-primary hover:text-primary-dark">
            Chores
          </Link>
          {user.is_admin && (
            <Link
              to="/admin/users"
              className="text-sm font-bold text-primary hover:text-primary-dark"
            >
              Admin
            </Link>
          )}
          <span className="hidden text-sm font-medium text-muted-foreground sm:inline">
            {user.name}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="font-bold text-muted-foreground hover:text-foreground"
            onClick={() => void logout()}
          >
            Log out
          </Button>
        </nav>
      </div>
    </header>
  )
}
