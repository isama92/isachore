import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { fullName } from '../lib/user'
import { Button } from '@/components/ui/button'

export default function Home() {
  const { user } = useAuth()
  const { t } = useTranslation()
  return (
    <main className="grid min-h-[calc(100dvh-57px)] place-items-center px-7">
      <div className="text-center">
        <h1 className="font-display text-3xl font-bold tracking-tight">
          {user ? t('home.greeting', { name: fullName(user) }) : 'isachore'}
        </h1>
        <p className="mt-2 font-medium text-muted-foreground">{t('home.placeholder')}</p>
        <Button asChild size="lg" className="mt-6">
          <Link to="/chores">{t('home.manageChores')}</Link>
        </Button>
      </div>
    </main>
  )
}
