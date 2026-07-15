import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'

export default function TopBar() {
  const { user, logout } = useAuth()
  if (!user) return null

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
