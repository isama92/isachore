import { Link } from 'react-router'
import { useAuth } from '../auth/useAuth'

export default function Home() {
  const { user } = useAuth()
  return (
    <main className="grid min-h-[calc(100dvh-57px)] place-items-center px-7">
      <div className="text-center">
        <h1 className="font-display text-3xl font-bold tracking-tight">
          {user ? `Hi ${user.name}` : 'isachore'}
        </h1>
        <p className="mt-2 font-medium text-muted-foreground">
          Your due view lands here soon. For now, manage the household chores.
        </p>
        <Link
          to="/chores"
          className="mt-6 inline-block rounded-button bg-primary px-5 py-2.5 text-sm font-extrabold text-white shadow-glow hover:bg-primary-dark"
        >
          Manage chores
        </Link>
      </div>
    </main>
  )
}
