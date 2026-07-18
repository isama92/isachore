import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { format } from 'date-fns'
import { CalendarIcon } from 'lucide-react'
import { ApiError } from '@/lib/api'
import { assignmentOptions, formatDate, repeatOptions } from '@/lib/chores'
import { fullName } from '@/lib/user'
import type { AssignmentType, HouseholdMember, RepeatPeriod, Tag } from '@/lib/types'
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
import { TagMultiSelect } from '@/components/chores/TagMultiSelect'

export type ChoreFormValues = {
  title: string
  description: string
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  assignee_ids: number[]
  tag_ids: number[]
}

// The API-ready payload (minus household_id, which the create page owns and the
// edit page never changes).
export type ChoreSubmit = {
  title: string
  description: string | null
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  assignee_ids: number[]
  tag_ids: number[]
}

type Props = {
  // Members and tags of the household the chore belongs to; the create page
  // swaps these when the household select changes.
  members: HouseholdMember[]
  tags: Tag[]
  initial: ChoreFormValues
  submitLabel: string
  cancelTo: string
  // Fallback error text (create vs edit differ).
  errorMessage: string
  // Rendered above the fields: the household select (create) or the read-only
  // household name (edit).
  header?: ReactNode
  // Must navigate away on success: the form only clears its saving state on
  // error, so a successful submit is expected to unmount the form.
  onSubmit: (values: ChoreSubmit) => Promise<void>
}

// Brand pill styling for the assignee/tag ToggleGroupItems; the on/off look is
// driven by data-[state=on] instead of a selected flag.
const chipItemClass =
  'flex h-auto items-center gap-2 rounded-full border-[1.5px] border-line bg-card px-3 py-1.5 text-sm font-bold text-muted-foreground hover:border-primary hover:bg-card hover:text-muted-foreground data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground'

// Shared field set for creating and editing a chore (both dedicated pages).
export function ChoreForm({
  members,
  tags,
  initial,
  submitLabel,
  cancelTo,
  errorMessage,
  header,
  onSubmit,
}: Props) {
  const { t } = useTranslation()
  const [values, setValues] = useState<ChoreFormValues>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dateOpen, setDateOpen] = useState(false)

  // Derive the selections against the current household's members/tags so a
  // household switch (create) drops assignees/tags that no longer apply, without
  // a state-setting effect.
  const memberIds = new Set(members.map((m) => m.id))
  const tagIds = new Set(tags.map((tag) => tag.id))
  const selectedAssignees = values.assignee_ids.filter((id) => memberIds.has(id))
  const selectedTags = values.tag_ids.filter((id) => tagIds.has(id))

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit({
        title: values.title,
        description: values.description || null,
        start_date: values.start_date,
        repeats: values.repeats,
        assignment_type: values.assignment_type,
        assignee_ids: selectedAssignees,
        tag_ids: selectedTags,
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : errorMessage)
      setSaving(false)
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-5">
      {header}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="title">{t('choreCreate.titleLabel')}</Label>
        <Input
          id="title"
          required
          value={values.title}
          onChange={(e) => setValues({ ...values, title: e.target.value })}
          placeholder={t('choreCreate.titlePlaceholder')}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="description">{t('choreCreate.description')}</Label>
        <Textarea
          id="description"
          value={values.description}
          onChange={(e) => setValues({ ...values, description: e.target.value })}
          placeholder={t('choreCreate.descriptionPlaceholder')}
          rows={3}
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label id="assignees-label">{t('choreCreate.assignees')}</Label>
        {members.length === 0 ? (
          <p className="text-sm font-medium text-muted-foreground">{t('choreCreate.noMembers')}</p>
        ) : (
          <ToggleGroup
            type="multiple"
            aria-labelledby="assignees-label"
            value={selectedAssignees.map(String)}
            onValueChange={(ids) => setValues((v) => ({ ...v, assignee_ids: ids.map(Number) }))}
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
            value={values.assignment_type}
            onValueChange={(v) => setValues({ ...values, assignment_type: v as AssignmentType })}
          >
            <SelectTrigger id="assignment" aria-labelledby="assignment-label" className="w-full">
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
            value={values.repeats}
            onValueChange={(v) => setValues({ ...values, repeats: v as RepeatPeriod })}
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
              <span id="start-date-value">{formatDate(values.start_date)}</span>
              <CalendarIcon className="size-4 text-muted-foreground" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="single"
              required
              selected={new Date(`${values.start_date}T00:00:00`)}
              onSelect={(d) => {
                if (d) setValues({ ...values, start_date: format(d, 'yyyy-MM-dd') })
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
          <TagMultiSelect
            tags={tags}
            value={selectedTags}
            onChange={(ids) => setValues((v) => ({ ...v, tag_ids: ids }))}
            labelledBy="tags-label"
          />
        )}
      </div>

      {error && <p className="text-[13px] font-bold text-danger">{error}</p>}

      <div className="flex gap-3">
        <Button type="submit" size="lg" disabled={saving}>
          {saving ? t('common.saving') : submitLabel}
        </Button>
        <Button asChild variant="ghost" size="lg">
          <Link to={cancelTo}>{t('common.cancel')}</Link>
        </Button>
      </div>
    </form>
  )
}
