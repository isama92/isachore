import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { format } from 'date-fns'
import { CalendarIcon } from 'lucide-react'
import { toast } from 'sonner'
import { api, ApiError } from '../lib/api'
import { assignmentOptions, formatDate, repeatOptions, todayISO } from '../lib/chores'
import { fullName } from '../lib/user'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type {
  AssignmentType,
  Chore,
  Household,
  HouseholdMember,
  RepeatPeriod,
  Tag,
} from '../lib/types'

type FormState = {
  title: string
  description: string
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  assignee_ids: number[]
  tag_ids: number[]
}

// Brand pill styling for the assignee/tag ToggleGroupItems; the on/off look is
// driven by data-[state=on] instead of a selected flag.
const chipItemClass =
  'flex h-auto items-center gap-2 rounded-full border-[1.5px] border-line bg-card px-3 py-1.5 text-sm font-bold text-muted-foreground hover:border-primary hover:bg-card hover:text-muted-foreground data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground'

export default function ChoreCreate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [members, setMembers] = useState<HouseholdMember[]>([])
  const [tags, setTags] = useState<Tag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [dateOpen, setDateOpen] = useState(false)
  const [form, setForm] = useState<FormState>(() => ({
    title: '',
    description: '',
    start_date: todayISO(),
    repeats: 'weekly',
    assignment_type: 'manual',
    assignee_ids: [],
    tag_ids: [],
  }))

  useEffect(() => {
    let cancelled = false
    Promise.all([api.get<Household[]>('/api/v1/households'), api.get<Tag[]>('/api/v1/tags')])
      .then(([households, tagList]) => {
        if (cancelled) return
        setMembers(households[0]?.members ?? [])
        setTags(tagList)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : t('choreCreate.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.post<Chore>('/api/v1/chores', {
        title: form.title,
        description: form.description || null,
        start_date: form.start_date,
        repeats: form.repeats,
        assignment_type: form.assignment_type,
        assignee_ids: form.assignee_ids,
        tag_ids: form.tag_ids,
      })
      toast.success(t('choreCreate.created'))
      await navigate('/chores')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('choreCreate.createError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className="mx-auto max-w-lg px-5 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {t('choreCreate.title')}
      </h1>

      {loading ? (
        <p className="font-medium text-muted-foreground">{t('common.loading')}</p>
      ) : (
        <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="title">{t('choreCreate.titleLabel')}</Label>
            <Input
              id="title"
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder={t('choreCreate.titlePlaceholder')}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="notes">{t('choreCreate.notes')}</Label>
            <Textarea
              id="notes"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder={t('choreCreate.notesPlaceholder')}
              rows={3}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label id="assignees-label">{t('choreCreate.assignees')}</Label>
            {members.length === 0 ? (
              <p className="text-sm font-medium text-muted-foreground">
                {t('choreCreate.noMembers')}
              </p>
            ) : (
              <ToggleGroup
                type="multiple"
                aria-labelledby="assignees-label"
                value={form.assignee_ids.map(String)}
                onValueChange={(ids) => setForm((f) => ({ ...f, assignee_ids: ids.map(Number) }))}
                className="w-full flex-wrap"
              >
                {members.map((m) => (
                  <ToggleGroupItem key={m.id} value={String(m.id)} className={chipItemClass}>
                    {fullName(m)}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label id="assignment-label" htmlFor="assignment">
                {t('choreCreate.assignment')}
              </Label>
              <Select
                value={form.assignment_type}
                onValueChange={(v) => setForm({ ...form, assignment_type: v as AssignmentType })}
              >
                <SelectTrigger
                  id="assignment"
                  aria-labelledby="assignment-label"
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {assignmentOptions.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`options.assignment.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label id="repeats-label" htmlFor="repeats">
                {t('choreCreate.repeats')}
              </Label>
              <Select
                value={form.repeats}
                onValueChange={(v) => setForm({ ...form, repeats: v as RepeatPeriod })}
              >
                <SelectTrigger id="repeats" aria-labelledby="repeats-label" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {repeatOptions.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`options.repeat.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label id="start-date-label" htmlFor="start-date">
              {t('choreCreate.startDate')}
            </Label>
            <Popover open={dateOpen} onOpenChange={setDateOpen}>
              <PopoverTrigger asChild>
                <button
                  id="start-date"
                  type="button"
                  aria-labelledby="start-date-label start-date-value"
                  className="flex h-10 w-full items-center justify-between rounded-input border border-input bg-transparent px-3 text-base outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:bg-input/30"
                >
                  <span id="start-date-value">{formatDate(form.start_date)}</span>
                  <CalendarIcon className="size-4 text-muted-foreground" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="start">
                <Calendar
                  mode="single"
                  required
                  selected={new Date(`${form.start_date}T00:00:00`)}
                  onSelect={(d) => {
                    if (d) setForm({ ...form, start_date: format(d, 'yyyy-MM-dd') })
                    setDateOpen(false)
                  }}
                  autoFocus
                />
              </PopoverContent>
            </Popover>
          </div>

          <div className="flex flex-col gap-2">
            <Label id="tags-label">{t('choreCreate.tags')}</Label>
            {tags.length === 0 ? (
              <p className="text-sm font-medium text-muted-foreground">{t('choreCreate.noTags')}</p>
            ) : (
              <ToggleGroup
                type="multiple"
                aria-labelledby="tags-label"
                value={form.tag_ids.map(String)}
                onValueChange={(ids) => setForm((f) => ({ ...f, tag_ids: ids.map(Number) }))}
                className="w-full flex-wrap"
              >
                {tags.map((t) => (
                  <ToggleGroupItem key={t.id} value={String(t.id)} className={chipItemClass}>
                    <span
                      className="inline-block size-2.5 rounded-full"
                      style={{ backgroundColor: t.color }}
                    />
                    {t.name}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}
          </div>

          {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

          <div className="flex gap-3">
            <Button type="submit" size="lg" disabled={saving}>
              {saving ? t('common.saving') : t('choreCreate.submit')}
            </Button>
            <Button asChild variant="ghost" size="lg">
              <Link to="/chores">{t('common.cancel')}</Link>
            </Button>
          </div>
        </form>
      )}
    </main>
  )
}
