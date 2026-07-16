import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { api } from '../lib/api'

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
            <button
              onClick={() => void returnToAdmin()}
              className="rounded-full bg-danger/10 px-3 py-1 text-[12px] font-bold text-danger hover:bg-danger/20"
            >
              Return to admin
            </button>
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
          <span className="hidden text-sm font-medium text-muted sm:inline">{user.name}</span>
          <button
            onClick={() => void logout()}
            className="text-sm font-bold text-muted hover:text-ink"
          >
            Log out
          </button>
        </nav>
      </div>
    </header>
  )
}
