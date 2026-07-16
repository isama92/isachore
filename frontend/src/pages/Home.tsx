import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { fullName } from '../lib/user'
import { Button } from '@/components/ui/button'

export default function Home() {
  const { user } = useAuth()
  return (
    <main className="grid min-h-[calc(100dvh-57px)] place-items-center px-7">
      <div className="text-center">
        <h1 className="font-display text-3xl font-bold tracking-tight">
          {user ? `Hi ${fullName(user)}` : 'isachore'}
        </h1>
        <p className="mt-2 font-medium text-muted-foreground">
          Your due view lands here soon. For now, manage the household chores.
        </p>
        <Button asChild size="lg" className="mt-6">
          <Link to="/chores">Manage chores</Link>
        </Button>
      </div>
    </main>
  )
}
