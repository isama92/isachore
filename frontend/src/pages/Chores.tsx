import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, ApiError } from '../lib/api'
import { assignmentLabel, formatDate, repeatLabel } from '../lib/chores'
import type { Chore } from '../lib/types'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'

const chipClass = 'rounded-full px-2.5 py-0.5 text-[11px] font-bold'

export default function Chores() {
  const [chores, setChores] = useState<Chore[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    () =>
      api
        .get<Chore[]>('/api/v1/chores')
        .then((data) => setChores(data))
        .catch((err: unknown) => {
          setError(err instanceof ApiError ? err.message : 'Failed to load chores')
        })
        .finally(() => setLoading(false)),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  async function remove(chore: Chore) {
    setError(null)
    try {
      await api.del(`/api/v1/chores/${chore.id}`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed')
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-2xl font-bold tracking-tight">Chores</h1>
        <Button asChild size="lg">
          <Link to="/chores/new">New chore</Link>
        </Button>
      </div>

      {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}

      {loading ? (
        <p className="font-medium text-muted-foreground">Loading…</p>
      ) : chores.length === 0 ? (
        <div className="rounded-2xl border border-line bg-card p-10 text-center">
          <p className="font-semibold text-ink">No chores yet.</p>
          <p className="mt-1 text-sm font-medium text-muted-foreground">
            Add the first one with New chore above.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-line bg-card">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead>
              <tr className="border-b border-line text-[11.5px] font-bold tracking-wide text-muted-foreground uppercase">
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Assignees</th>
                <th className="px-4 py-3">Repeats</th>
                <th className="px-4 py-3">Assignment</th>
                <th className="px-4 py-3">Tags</th>
                <th className="px-4 py-3">Start</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {chores.map((c) => (
                <tr key={c.id} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-3 font-semibold">{c.title}</td>
                  <td className="px-4 py-3">
                    {c.assignees.length === 0 ? (
                      <span className="text-muted-foreground">Unassigned</span>
                    ) : (
                      <span className="flex flex-wrap gap-1.5">
                        {c.assignees.map((a) => (
                          <span key={a.id} className={`${chipClass} bg-page text-ink`}>
                            {a.name}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`${chipClass} bg-page text-primary-dark`}>
                      {repeatLabel(c.repeats)}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-medium text-muted-foreground">
                    {assignmentLabel(c.assignment_type)}
                  </td>
                  <td className="px-4 py-3">
                    {c.tags.length === 0 ? (
                      <span className="text-muted-foreground">None</span>
                    ) : (
                      <span className="flex flex-wrap items-center gap-2">
                        {c.tags.map((t) => (
                          <span
                            key={t.id}
                            className="flex items-center gap-1.5 text-[13px] font-semibold"
                          >
                            <span
                              className="inline-block size-2.5 rounded-full"
                              style={{ backgroundColor: t.color }}
                            />
                            {t.name}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-medium text-muted-foreground whitespace-nowrap">
                    {formatDate(c.start_date)}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="h-auto p-0 font-bold text-destructive hover:no-underline hover:opacity-80"
                        >
                          Delete
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete “{c.title}”?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This chore will be permanently removed. This cannot be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction variant="destructive" onClick={() => void remove(c)}>
                            Delete chore
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
