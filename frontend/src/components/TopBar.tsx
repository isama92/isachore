import { useTranslation } from 'react-i18next'
import { PanelLeft } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '../auth/useAuth'
import { api } from '../lib/api'
import { endpoints } from '../lib/endpoints'
import { Button } from '@/components/ui/button'
import { useSidebar } from '@/components/ui/sidebar'

export default function TopBar() {
  const { user, impersonating, refresh } = useAuth()
  const { t } = useTranslation()
  const { toggleSidebar } = useSidebar()
  if (!user) return null

  async function returnToAdmin() {
    try {
      await api.post(endpoints.auth.stopImpersonating)
      toast.success(t('topbar.backToAccount'))
    } catch {
      // If the parked admin session has expired the server ends both sessions
      // and returns 401; refresh() below then reflects the logged-out state and
      // RequireAuth sends the operator to login.
    } finally {
      await refresh()
    }
  }

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-card px-4">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={toggleSidebar}
        aria-label={t('sidebar.toggle')}
      >
        <PanelLeft />
      </Button>
      {impersonating && (
        <Button
          type="button"
          variant="destructive"
          size="sm"
          className="ml-auto rounded-full font-bold"
          onClick={() => void returnToAdmin()}
        >
          {t('topbar.returnToAdmin')}
        </Button>
      )}
    </header>
  )
}
