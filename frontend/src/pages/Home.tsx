import { Link } from 'react-router'

export default function Home() {
  return (
    <main className="grid min-h-dvh place-items-center px-7">
      <div className="text-center">
        <h1 className="font-display text-3xl font-bold tracking-tight">Hello world</h1>
        <p className="mt-2 font-medium text-muted">isachore — chores UI coming soon.</p>
        <Link
          to="/login"
          className="mt-4 inline-block font-bold text-primary hover:text-primary-dark"
        >
          Go to login
        </Link>
      </div>
    </main>
  )
}
