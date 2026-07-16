import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { formatDate } from '../lib/chores'
import { fullName } from '../lib/user'
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
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export default function Chores() {
  const { t } = useTranslation()
  const [chores, setChores] = useState<Chore[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    () =>
      api
        .get<Chore[]>('/api/v1/chores')
        .then((data) => setChores(data))
        .catch((err: unknown) => {
          setError(err instanceof ApiError ? err.message : t('chores.loadError'))
        })
        .finally(() => setLoading(false)),
    [t],
  )

  useEffect(() => {
    void load()
  }, [load])

  async function remove(chore: Chore) {
    setError(null)
    try {
      await api.del(`/api/v1/chores/${chore.id}`)
      toast.success(t('chores.deleted'))
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('chores.deleteError'))
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-5 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-2xl font-bold tracking-tight">{t('chores.title')}</h1>
        <Button asChild size="lg">
          <Link to="/chores/new">{t('chores.new')}</Link>
        </Button>
      </div>

      {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : chores.length === 0 ? (
        <div className="rounded-2xl border border-line bg-card p-10 text-center">
          <p className="font-semibold text-ink">{t('chores.empty')}</p>
          <p className="mt-1 text-sm font-medium text-muted-foreground">{t('chores.emptyHint')}</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-card">
          <Table className="min-w-[720px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>{t('chores.headers.title')}</TableHead>
                <TableHead>{t('chores.headers.assignees')}</TableHead>
                <TableHead>{t('chores.headers.repeats')}</TableHead>
                <TableHead>{t('chores.headers.assignment')}</TableHead>
                <TableHead>{t('chores.headers.tags')}</TableHead>
                <TableHead>{t('chores.headers.start')}</TableHead>
                <TableHead className="text-right">{t('chores.headers.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {chores.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-semibold">{c.title}</TableCell>
                  <TableCell>
                    {c.assignees.length === 0 ? (
                      <span className="text-muted-foreground">{t('chores.unassigned')}</span>
                    ) : (
                      <span className="flex flex-wrap gap-1.5">
                        {c.assignees.map((a) => (
                          <Badge key={a.id} variant="secondary">
                            {fullName(a)}
                          </Badge>
                        ))}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="text-primary">
                      {t(`options.repeat.${c.repeats}`)}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium text-muted-foreground">
                    {t(`options.assignment.${c.assignment_type}`)}
                  </TableCell>
                  <TableCell>
                    {c.tags.length === 0 ? (
                      <span className="text-muted-foreground">{t('chores.noTags')}</span>
                    ) : (
                      <span className="flex flex-wrap items-center gap-2">
                        {c.tags.map((tag) => (
                          <span
                            key={tag.id}
                            className="flex items-center gap-1.5 text-[13px] font-semibold"
                          >
                            <span
                              className="inline-block size-2.5 rounded-full"
                              style={{ backgroundColor: tag.color }}
                            />
                            {tag.name}
                          </span>
                        ))}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium text-muted-foreground">
                    {formatDate(c.start_date)}
                  </TableCell>
                  <TableCell className="text-right">
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="h-auto p-0 font-bold text-destructive hover:no-underline hover:opacity-80"
                        >
                          {t('chores.delete')}
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>
                            {t('chores.deleteConfirm', { title: c.title })}
                          </AlertDialogTitle>
                          <AlertDialogDescription>
                            {t('chores.deleteConfirmBody')}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                          <AlertDialogAction variant="destructive" onClick={() => void remove(c)}>
                            {t('chores.deleteConfirmAction')}
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </main>
  )
}
