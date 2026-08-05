import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { format } from 'date-fns'
import { CalendarIcon } from 'lucide-react'
import { ApiError } from '@/lib/api'
import {
  MAX_REPEAT_INTERVAL,
  assignmentOptions,
  formatDate,
  repeatOptions,
  todayISO,
} from '@/lib/chores'
import type { AssignmentType, HouseholdMember, RepeatPeriod, Tag } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { TagMultiSelect } from '@/components/chores/TagMultiSelect'
import { WeekdayPicker } from '@/components/chores/WeekdayPicker'
import { AssigneeMultiSelect } from '@/components/chores/AssigneeMultiSelect'
import RichTextEditor from '@/components/rich-text/RichTextEditor'

// The "nobody" option's value in the current-assignee Select. A sentinel because Radix reserves
// the empty string for "no value selected", so an <SelectItem value=""> renders as the
// placeholder rather than as something you can pick. Never sent to the API: it maps to the
// clear_current_assignee flag.
const UNASSIGNED = 'unassigned'

export type ChoreFormValues = {
  title: string
  // Sanitised HTML, not plain text. '' means "no description", which holds because
  // RichTextEditor emits '' rather than the `<p></p>` Tiptap actually keeps for an untouched
  // document - so the `|| null` in handleSubmit stays correct. The backend collapses
  // visually-empty HTML to NULL as well, for clients that are not this form.
  description: string
  start_date: string
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  // Completions per assignee before a handoff (1 = every completion). "Take turns"
  // is on when this is > 1.
  turn_length: number
  // Periods between occurrences (1 = every period). Read only to seed the
  // string-backed input below, the same way turn_length is.
  repeat_interval: number
  // Pinned weekdays for a weekly chore, 0 = Monday .. 6 = Sunday. Empty is the
  // form's spelling of the API's null: unpinned.
  weekdays: number[]
  assignee_ids: number[]
  // Who is on the hook right now. Always meaningful for `manual`; for the auto
  // strategies it is only editable where the page allows it (see
  // allowAssigneeOverride), and then only until the next completion re-derives it.
  current_assignee_id: number | null
  // Hand the chore back to the whole household. Separate from a null current_assignee_id,
  // which means "no opinion" and deliberately keeps whoever is already on the hook - see the
  // field's comment in backend/app/schemas/chore.py for why the two cannot be merged.
  clear_current_assignee: boolean
  tag_ids: number[]
}

// The API-ready payload (minus household_id, which the create page owns and the
// edit page never changes).
export type ChoreSubmit = {
  title: string
  description: string | null
  // null for an unscheduled chore, which has no start date (the same asymmetry as
  // description and weekdays below: the form holds '' where the API wants null).
  start_date: string | null
  repeats: RepeatPeriod
  assignment_type: AssignmentType
  turn_length: number
  repeat_interval: number
  // null rather than [] when the period is not weekly or nothing is pinned (the
  // same asymmetry as description: string -> string | null above).
  weekdays: number[] | null
  assignee_ids: number[]
  current_assignee_id: number | null
  clear_current_assignee: boolean
  tag_ids: number[]
}

type Props = {
  // Members and tags of the household the chore belongs to; the create page
  // swaps these when the household select changes.
  members: HouseholdMember[]
  tags: Tag[]
  // The chosen household's IANA zone. `start_date` is a calendar date the backend reads in
  // it, so "today" has to mean the household's today, not the viewer's.
  //
  // Known limitation: this drives the manual -> recurring refill below, but NOT a date already
  // populated at mount. Switching household on the create page therefore keeps the first
  // household's "today", which where the two zones straddle midnight is a day out. Left alone
  // deliberately: refilling it would need a setState in an effect (banned here, see the eslint
  // note in CLAUDE.md) or a remount that discards whatever the user has typed, and the field is
  // visible and editable, so the wrong value is on screen rather than hidden.
  timezone?: string
  initial: ChoreFormValues
  submitLabel: string
  cancelTo: string
  // Fallback error text (create vs edit differ).
  errorMessage: string
  // Rendered above the fields: the household select (create) or the read-only
  // household name (edit).
  header?: ReactNode
  // Let the current assignee be changed whatever the assignment strategy. The API
  // honours an explicit pool member for all of them, so this is only about which
  // page offers it: edit does, because moving a chore off whoever is stuck with it
  // is the point; create does not, so a random chore's first assignee stays random.
  allowAssigneeOverride?: boolean
  // Must navigate away on success: the form only clears its saving state on
  // error, so a successful submit is expected to unmount the form.
  onSubmit: (values: ChoreSubmit) => Promise<void>
}

// Shared field set for creating and editing a chore (both dedicated pages).
export function ChoreForm({
  members,
  tags,
  timezone,
  initial,
  submitLabel,
  cancelTo,
  errorMessage,
  header,
  allowAssigneeOverride = false,
  onSubmit,
}: Props) {
  const { t } = useTranslation()
  const [values, setValues] = useState<ChoreFormValues>(initial)
  // "Take turns" is its own toggle (not derived from turn_length) so editing the
  // number down to 1 doesn't make the field vanish; the input is string-backed so it
  // can be cleared and multi-digit values typed, then parsed/clamped on submit.
  const [takeTurns, setTakeTurns] = useState(() => initial.turn_length > 1)
  const [turnLength, setTurnLength] = useState(() =>
    String(initial.turn_length > 1 ? initial.turn_length : 2),
  )
  // String-backed for the same reasons as turnLength: it can be cleared and typed into
  // multi-digit, then parsed and clamped on submit.
  const [repeatInterval, setRepeatInterval] = useState(() => String(initial.repeat_interval))
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

  // "Take turns" only applies to the auto-rotating strategies; manual instead lets
  // you pick the current person (from the selected pool). Derived so switching
  // strategy or dropping the current assignee can't submit a stale value.
  // The date the form is actually working with: whatever the user picked, else today in the
  // household's zone. Derived rather than stored, which is what makes switching household on the
  // create page follow the new zone instead of keeping the first one's "today" - and it removes
  // the period select's refill branch, since an empty value now resolves on its own.
  const startDate = values.start_date || todayISO(timezone)

  const isManual = values.assignment_type === 'manual'
  const currentAssigneeId =
    values.current_assignee_id !== null && selectedAssignees.includes(values.current_assignee_id)
      ? values.current_assignee_id
      : null
  // Manual always offers the picker, since nothing else would ever set an assignee.
  // The auto strategies only offer it where the caller asks (the edit page), and
  // there it is a one-turn override: the next completion re-derives from the
  // strategy, which the hint below says out loud.
  const canPickAssignee = isManual || allowAssigneeOverride
  const showAssigneePicker = canPickAssignee && selectedAssignees.length > 0

  // Recurrence, derived for the same reason: switching period must not submit stale
  // detail. NOTE `isManual` above is the *assignment strategy*; `manualRepeat` here is
  // the repeat period, which has its own `manual` value. They are different fields.
  const manualRepeat = values.repeats === 'manual'
  const isWeekly = values.repeats === 'weekly'
  const interval = manualRepeat
    ? 1
    : Math.min(MAX_REPEAT_INTERVAL, Math.max(1, Math.trunc(Number(repeatInterval)) || 1))
  const weekdays = isWeekly ? values.weekdays : []
  // The noun beside the interval input. Empty when unscheduled, whose field is hidden, so
  // the fallback never renders. Shares `interval` with the payload, so the word always
  // agrees with what will be saved. Compares `values.repeats` inline rather than reusing
  // `manualRepeat`: TypeScript will not narrow the union through the aliased boolean, and
  // there is deliberately no options.repeatUnit.manual key for it to resolve to.
  const intervalUnit =
    values.repeats === 'manual'
      ? ''
      : t(`options.repeatUnit.${values.repeats}`, { count: interval })

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit({
        title: values.title,
        description: values.description || null,
        // An unscheduled chore has no start date: its field is hidden above and the API
        // would drop the value anyway, so send the null explicitly.
        start_date: manualRepeat ? null : startDate,
        repeats: values.repeats,
        assignment_type: values.assignment_type,
        // A whole number >= 2 when taking turns, otherwise 1 (hand off every completion).
        turn_length: isManual || !takeTurns ? 1 : Math.max(2, Math.trunc(Number(turnLength)) || 2),
        repeat_interval: interval,
        // null both when the period is not weekly and when nothing is pinned: the API
        // treats both as unpinned. Since ChoreUpdate is a full replace, this is also how
        // clearing every day unpins an existing chore.
        weekdays: weekdays.length > 0 ? weekdays : null,
        assignee_ids: selectedAssignees,
        current_assignee_id: canPickAssignee ? currentAssigneeId : null,
        // Gated on the same condition as current_assignee_id, and for the same reason: the
        // choice is only meaningful where the picker offers it, so a hidden picker must not
        // smuggle an unassign through. Note it is NOT gated on the pool, which is what lets
        // "clear" survive an edit that also empties the pool - the two agree, since an empty
        // pool is unassigned anyway.
        clear_current_assignee: canPickAssignee && values.clear_current_assignee,
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

      {/* gap-2, not gap-1.5: the editor is a bordered composite like the pickers below, not a
          bare input. Labelled by id rather than htmlFor, because the field is a contenteditable
          and so not a labelable element (same as the assignee and weekday pickers). */}
      <div className="flex flex-col gap-2">
        <Label id="description-label">{t('choreCreate.description')}</Label>
        <RichTextEditor
          value={values.description}
          onChange={(html) => setValues((v) => ({ ...v, description: html }))}
          labelledBy="description-label"
          placeholder={t('choreCreate.descriptionPlaceholder')}
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label id="assignees-label">{t('choreCreate.assignees')}</Label>
        {members.length === 0 ? (
          <p className="text-sm font-medium text-muted-foreground">{t('choreCreate.noMembers')}</p>
        ) : (
          <AssigneeMultiSelect
            members={members}
            value={selectedAssignees}
            onChange={(ids) => setValues((v) => ({ ...v, assignee_ids: ids }))}
            labelledBy="assignees-label"
            placeholder={t('choreCreate.assigneesPlaceholder')}
            searchPlaceholder={t('choreCreate.assigneesSearch')}
            emptyText={t('choreCreate.assigneesEmpty')}
          />
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
            onValueChange={(v) => {
              const repeats = v as RepeatPeriod
              setValues({ ...values, repeats })
            }}
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

      {/* Recurrence detail: how many periods between occurrences, and for a weekly chore
          which weekdays it lands on. An unscheduled chore never recurs, so neither applies. Sits
          right under the Repeats select, which is the grid's last element once it
          collapses to one column below sm. */}
      {!manualRepeat && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label id="repeat-interval-label" htmlFor="repeat-interval">
              {t('choreCreate.repeatInterval')}
            </Label>
            <div className="flex items-center gap-2">
              <Input
                id="repeat-interval"
                aria-labelledby="repeat-interval-label"
                type="number"
                min={1}
                max={MAX_REPEAT_INTERVAL}
                step={1}
                className="w-24"
                value={repeatInterval}
                onChange={(e) => setRepeatInterval(e.target.value)}
              />
              <span className="text-sm font-medium text-muted-foreground">{intervalUnit}</span>
            </div>
          </div>

          {isWeekly && (
            <div className="flex flex-col gap-2">
              <Label id="weekdays-label">{t('choreCreate.weekdays')}</Label>
              <WeekdayPicker
                value={weekdays}
                onChange={(days) => setValues((v) => ({ ...v, weekdays: days }))}
                labelledBy="weekdays-label"
              />
              <p className="text-[13px] font-medium text-muted-foreground">
                {t('choreCreate.weekdaysHint')}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Take turns: only for the auto-rotating strategies (manual never rotates). */}
      {!isManual && (
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox
              checked={takeTurns}
              onCheckedChange={(checked) => setTakeTurns(checked === true)}
            />
            {t('choreCreate.takeTurns')}
          </label>
          {takeTurns && (
            <div className="flex flex-col gap-1.5">
              <Label id="turn-length-label" htmlFor="turn-length">
                {t('choreCreate.turnLength')}
              </Label>
              <Input
                id="turn-length"
                aria-labelledby="turn-length-label"
                type="number"
                min={2}
                step={1}
                value={turnLength}
                onChange={(e) => setTurnLength(e.target.value)}
              />
              <p className="text-[13px] font-medium text-muted-foreground">
                {t('choreCreate.turnLengthHint')}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Who is currently on the hook, picked from the selected pool. */}
      {showAssigneePicker && (
        <div className="flex flex-col gap-1.5">
          <Label id="current-assignee-label" htmlFor="current-assignee">
            {t('choreCreate.currentAssignee')}
          </Label>
          <Select
            value={
              values.clear_current_assignee
                ? UNASSIGNED
                : currentAssigneeId !== null
                  ? String(currentAssigneeId)
                  : undefined
            }
            onValueChange={(v) =>
              setValues({
                ...values,
                clear_current_assignee: v === UNASSIGNED,
                current_assignee_id: v === UNASSIGNED ? null : Number(v),
              })
            }
          >
            <SelectTrigger
              id="current-assignee"
              aria-labelledby="current-assignee-label"
              className="w-full"
            >
              <SelectValue placeholder={t('choreCreate.currentAssigneePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {/* Hand the chore back to the whole household. A sentinel rather than '', which
                  Radix reserves for "no value" and would render as the placeholder instead of a
                  selectable option. */}
              <SelectItem value={UNASSIGNED}>{t('choreCreate.currentAssigneeNobody')}</SelectItem>
              {selectedAssignees.map((id) => {
                const member = members.find((m) => m.id === id)
                return (
                  <SelectItem key={id} value={String(id)}>
                    {member ? `${member.first_name} ${member.last_name}` : String(id)}
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
          {values.clear_current_assignee && (
            <p className="text-[13px] font-medium text-muted-foreground">
              {t('choreCreate.currentAssigneeNobodyHint')}
            </p>
          )}
          {!isManual && (
            <p className="text-[13px] font-medium text-muted-foreground">
              {t('choreCreate.currentAssigneeTurnHint')}
            </p>
          )}
        </div>
      )}

      {/* An unscheduled chore starts nothing: it has no first due date to seed and never
          becomes due, so the field would be dead config on screen. Hidden rather than
          disabled, matching how the recurrence detail above disappears. `startDate` above is
          what this block renders, never `values.start_date`: an unscheduled chore stores no
          start date, so the raw value can be empty and the Calendar would choke on it. */}
      {!manualRepeat && (
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
                <span id="start-date-value">{formatDate(startDate)}</span>
                <CalendarIcon className="size-4 text-muted-foreground" />
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                required
                selected={new Date(`${startDate}T00:00:00`)}
                onSelect={(d) => {
                  if (d) setValues({ ...values, start_date: format(d, 'yyyy-MM-dd') })
                  setDateOpen(false)
                }}
                autoFocus
              />
            </PopoverContent>
          </Popover>
        </div>
      )}

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
