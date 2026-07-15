import { Link } from 'react-router'

export default function Login() {
  return (
    <main className="flex min-h-dvh items-center justify-center px-7 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex items-center gap-2.5">
          <div className="grid size-10 place-items-center rounded-xl bg-primary text-[22px] font-extrabold text-white shadow-logo">
            ✓
          </div>
          <span className="font-display text-[22px] font-extrabold tracking-tight">isachore</span>
        </div>

        <h1 className="font-display text-3xl leading-tight font-bold tracking-tight">
          Welcome back.
        </h1>
        <p className="mt-1.5 mb-7 text-[14.5px] font-medium text-muted">
          Sign in to see what your flat needs today.
        </p>

        <form className="flex flex-col gap-4" onSubmit={(e) => e.preventDefault()}>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11.5px] font-bold tracking-wide text-muted uppercase">
              Email
            </span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="you@example.com"
              className="rounded-input border-[1.5px] border-line bg-white px-4 py-3 text-[15px] font-semibold placeholder:font-medium placeholder:text-placeholder focus:border-primary focus:outline-none"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-[11.5px] font-bold tracking-wide text-muted uppercase">
              Password
            </span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              placeholder="••••••••••"
              className="rounded-input border-[1.5px] border-line bg-white px-4 py-3 text-[15px] font-semibold placeholder:font-medium placeholder:text-placeholder focus:border-primary focus:outline-none"
            />
          </label>

          <div className="text-right">
            <a href="#" className="text-[13px] font-bold text-primary hover:text-primary-dark">
              Forgot password?
            </a>
          </div>

          <button
            type="submit"
            className="rounded-button bg-primary p-[15px] text-[15.5px] font-extrabold text-white shadow-glow transition hover:bg-primary-dark"
          >
            Sign in
          </button>
        </form>

        <p className="mt-6 text-center text-[13.5px] font-medium text-muted">
          New here?{' '}
          <Link to="/login" className="font-extrabold text-primary-dark">
            Join your household
          </Link>
        </p>
      </div>
    </main>
  )
}
