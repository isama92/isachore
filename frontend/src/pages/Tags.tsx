import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { SquarePenIcon, Trash2Icon } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { Household, Page, Tag } from '../lib/types'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

export default function Tags() {
  const { t } = useTranslation()
  const [households, setHouseholds] = useState<Household[]>([])
  const [householdId, setHouseholdId] = useState<number | null>(null)
  const [tags, setTags] = useState<Tag[]>([])
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // Load the user's households once; default to the lowest-id one. Tags are
  // per-household, so (unlike chores) there is no "all households" view.
  useEffect(() => {
    let cancelled = false
    api
      .get<Page<Household>>('/api/v1/households?sort_by=id&sort_dir=asc&page_size=100')
      .then((page) => {
        if (cancelled) return
        setHouseholds(page.items)
        setHouseholdId(page.items[0]?.id ?? null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('tags.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  // Load the selected household's tags (and again after a delete).
  useEffect(() => {
    if (householdId === null) return
    let cancelled = false
    api
      .get<Tag[]>(`/api/v1/tags?household_id=${householdId}`)
      .then((list) => {
        if (!cancelled) setTags(list)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t('tags.loadError'))
      })
    return () => {
      cancelled = true
    }
  }, [householdId, reloadKey, t])

  async function remove(tag: Tag) {
    setError(null)
    try {
      await api.del(`/api/v1/tags/${tag.id}`)
      toast.success(t('tags.deleted'))
      setReloadKey((k) => k + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('tags.deleteError'))
    }
  }

  function deleteDialog(tag: Tag): ReactNode {
    const label = t('tags.delete')
    return (
      <AlertDialog>
        <Tooltip>
          <TooltipTrigger asChild>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={label}
                className="text-destructive hover:text-destructive"
              >
                <Trash2Icon />
              </Button>
            </AlertDialogTrigger>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('tags.deleteConfirm', { name: tag.name })}</AlertDialogTitle>
            <AlertDialogDescription>{t('tags.deleteConfirmBody')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove(tag)}>
              {t('tags.deleteConfirmAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  function rowActions(tag: Tag): ReactNode {
    const editLabel = t('tags.edit')
    return (
      <div className="flex items-center justify-end gap-0.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button asChild variant="ghost" size="icon-sm" aria-label={editLabel}>
              <Link to={`/tags/${tag.id}/edit`}>
                <SquarePenIcon />
              </Link>
            </Button>
          </TooltipTrigger>
          <TooltipContent>{editLabel}</TooltipContent>
        </Tooltip>
        {deleteDialog(tag)}
      </div>
    )
  }

  return (
    <TooltipProvider>
      <main className="mx-auto w-full max-w-3xl px-5 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold tracking-tight">{t('tags.title')}</h1>
          <Button asChild size="lg">
            <Link to="/tags/new">{t('tags.new')}</Link>
          </Button>
        </div>

        {households.length > 1 && (
          <div className="mb-4 flex flex-col gap-1.5">
            <Label id="household-label" htmlFor="household">
              {t('tags.filters.householdLabel')}
            </Label>
            <Select
              value={householdId !== null ? String(householdId) : undefined}
              onValueChange={(v) => setHouseholdId(Number(v))}
            >
              <SelectTrigger
                id="household"
                aria-label={t('tags.filters.householdLabel')}
                className="sm:w-56"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {households.map((h) => (
                  <SelectItem key={h.id} value={String(h.id)}>
                    {h.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {loading ? (
          <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
        ) : households.length === 0 ? (
          <p className="font-medium text-muted-foreground">{error ?? t('tags.noHouseholds')}</p>
        ) : (
          <>
            {error && <p className="mb-4 text-[13px] font-bold text-danger">{error}</p>}
            <div className="overflow-hidden rounded-2xl border border-line bg-card">
              <Table className="min-w-[420px]">
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>{t('tags.headers.name')}</TableHead>
                    <TableHead className="text-right">{t('tags.headers.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tags.length === 0 ? (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={2} className="h-24 text-center text-muted-foreground">
                        {t('tags.empty')}
                      </TableCell>
                    </TableRow>
                  ) : (
                    tags.map((tag) => (
                      <TableRow key={tag.id}>
                        <TableCell>
                          <span className="flex items-center gap-2.5 font-semibold">
                            <span
                              className="inline-block size-3 rounded-full"
                              style={{ backgroundColor: tag.color }}
                            />
                            {tag.name}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">{rowActions(tag)}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </main>
    </TooltipProvider>
  )
}
