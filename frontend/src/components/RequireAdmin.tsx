import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { routes } from '../lib/routes'

export default function RequireAdmin() {
  const { user } = useAuth()
  return user?.is_admin ? <Outlet /> : <Navigate to={routes.home} replace />
}
