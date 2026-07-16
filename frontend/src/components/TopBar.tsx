import { Moon, Sun } from 'lucide-react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { useTheme } from '../theme/useTheme'
import { api } from '../lib/api'
import { fullName, initials } from '../lib/user'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export default function TopBar() {
  const { user, impersonating, logout, refresh } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  if (!user) return null

  async function returnToAdmin() {
    try {
      await api.post('/api/v1/auth/stop-impersonating')
      toast.success('Back to your account')
    } catch {
      // If the parked admin session has expired the server ends both sessions
      // and returns 401; refresh() below then reflects the logged-out state and
      // RequireAuth sends the operator to login.
    } finally {
      await refresh()
    }
  }

  return (
    <header className="border-b border-line bg-card">
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
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Toggle theme"
            className="text-muted-foreground hover:text-foreground"
            onClick={toggleTheme}
          >
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="Open user menu"
                className="rounded-full outline-hidden focus-visible:ring-2 focus-visible:ring-primary/50"
              >
                <Avatar size="lg">
                  {user.avatar_url && <AvatarImage src={user.avatar_url} alt={fullName(user)} />}
                  <AvatarFallback className="bg-primary/10 font-bold text-primary">
                    {initials(user)}
                  </AvatarFallback>
                </Avatar>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel className="font-normal">
                <span className="block truncate text-sm font-bold text-foreground">
                  {fullName(user)}
                </span>
                <span className="block truncate text-xs font-medium text-muted-foreground">
                  {user.email}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => void navigate('/profile')}>
                Profile
              </DropdownMenuItem>
              {user.is_admin && (
                <DropdownMenuItem onSelect={() => void navigate('/admin/users')}>
                  Admin
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => void logout()}>
                Log out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </nav>
      </div>
    </header>
  )
}
